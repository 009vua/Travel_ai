import streamlit as st
import google.generativeai as genai
import openai
from PIL import Image, ImageFilter, ImageOps
from PIL.ExifTags import TAGS, GPSTAGS
import sqlite3
import os
import datetime
import requests
import hashlib
import shutil
import base64
import io

# ==========================================
# 1. KHỞI TẠO CẤU HÌNH MẶC ĐỊNH
# ==========================================
DEFAULT_PROMPT = """BẮT BUỘC TRẢ VỀ THEO ĐÚNG ĐỊNH DẠNG:
---KIDSLAND---

Đóng vai hiệu trưởng trường mầm non có 10 năm kinh nghiệm tuyển sinh.

Nhiệm vụ:

1. Quan sát thật kỹ bức ảnh.
2. Xác định đối tượng chính, hành động, cảm xúc và môi trường xung quanh.
3. Không mô tả ảnh đơn thuần.
4. Tìm ra một giá trị giáo dục hoặc bài học cuộc sống ẩn phía sau khoảnh khắc trong ảnh.
5. Ưu tiên các chủ đề:
   - sự tự lập
   - kỹ năng sống
   - lòng biết ơn
   - khả năng quan sát
   - tư duy khám phá
   - sự tự tin
   - tính kiên trì
   - tình yêu thiên nhiên
   - khả năng thích nghi
   - trưởng thành từng ngày

6. Viết bài Facebook từ 2-3 dòng.
7. Giọng văn chân thành, gần gũi, giàu cảm xúc và mang tính chiêm nghiệm.
8. Không quảng cáo lộ liễu.
9. Không kêu gọi đăng ký.
10. Mỗi bài phải khai thác một góc nhìn khác nhau để tránh lặp lại nội dung các ngày trước.
---
---MARKETING---

Đóng vai admin fanpage du lịch có 10 năm kinh nghiệm.

Phân tích bức ảnh dưới góc nhìn du lịch và trải nghiệm.

Trước tiên hãy xác định:

- thời tiết
- thời điểm trong ngày
- mùa trong năm (nếu có thể suy luận)
- địa điểm hoặc khu vực có khả năng cao nhất
- các dấu hiệu nhận biết trong ảnh

Sau đó viết một bài Facebook từ 3-5 dòng.

Không mô tả ảnh đơn thuần.

Hãy kể một cảm xúc, một câu chuyện hoặc một trải nghiệm mà du khách có thể cảm nhận khi đứng ở nơi đó.

Giọng văn tự nhiên, có tính địa phương, tạo cảm giác muốn khám phá.

Không quảng cáo lộ liễu.

Kết thúc bằng một câu ngắn gợi suy nghĩ hoặc khơi gợi mong muốn trải nghiệm.

Nếu không xác định được chính xác địa điểm thì nêu rõ đây là suy đoán dựa trên các dấu hiệu trong ảnh."""

# ==========================================
# 2. KHỞI TẠO HỆ THỐNG & SESSION STATE
# ==========================================
st.set_page_config(page_title="Facebook Content Studio", page_icon="📘", layout="wide")

if 'gemini_key' not in st.session_state:
    st.session_state.gemini_key = ""
if 'openai_key' not in st.session_state:
    st.session_state.openai_key = ""
if 'custom_prompt' not in st.session_state:
    st.session_state.custom_prompt = DEFAULT_PROMPT

UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

def init_db():
    conn = sqlite3.connect("travel_ai.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS posts
                 (id TEXT PRIMARY KEY, image_path TEXT,
                  exif_time TEXT, location_text TEXT,
                  content_kidsland TEXT, content_marketing TEXT,
                  created_at DATETIME)''')
    
    thirty_days_ago = datetime.datetime.now() - datetime.timedelta(days=30)
    c.execute("SELECT image_path FROM posts WHERE created_at < ?", (thirty_days_ago,))
    for row in c.fetchall():
        if os.path.exists(row[0]):
            try:
                os.remove(row[0])
            except: pass
    c.execute("DELETE FROM posts WHERE created_at < ?", (thirty_days_ago,))
    conn.commit()
    conn.close()

init_db()

# Cài đặt Sidebar (Mỗi người dùng tự nhập key riêng tư trên trình duyệt của họ)
with st.sidebar.expander("⚙️ Cài đặt API Keys", expanded=True):
    st.session_state.gemini_key = st.text_input(
        "Nhập Gemini API Key:", 
        value=st.session_state.gemini_key, 
        type="password",
        help="Key này chỉ lưu trên trình duyệt của riêng bạn, an toàn tuyệt đối."
    )
    st.session_state.openai_key = st.text_input(
        "Nhập ChatGPT (OpenAI) API Key:", 
        value=st.session_state.openai_key, 
        type="password",
        help="Key này chỉ lưu trên trình duyệt của riêng bạn."
    )
    st.markdown("[👉 Lấy Gemini Key](https://aistudio.google.com/app/apikey) | [👉 Lấy OpenAI Key](https://platform.openai.com/api-keys)")

st.title("📘 Facebook AI Content Studio")
st.caption("Ứng dụng đa người dùng - Tự do nhập API Key riêng - Xử lý ảnh thông minh")

# ==========================================
# 3. CÁC HÀM XỬ LÝ ẢNH & GỌI AI
# ==========================================
def encode_image_to_base64(image_path):
    img = ImageOps.exif_transpose(Image.open(image_path))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode('utf-8')

def analyze_image_with_ai(ai_provider, prompt_text, image_path):
    if ai_provider == "Google Gemini":
        if not st.session_state.gemini_key:
            raise Exception("Vui lòng nhập Gemini API Key ở thanh bên trái!")
        genai.configure(api_key=st.session_state.gemini_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        correct_img = ImageOps.exif_transpose(Image.open(image_path))
        response = model.generate_content([prompt_text, correct_img])
        return response.text
    elif ai_provider == "ChatGPT (OpenAI)":
        if not st.session_state.openai_key:
            raise Exception("Vui lòng nhập ChatGPT (OpenAI) API Key ở thanh bên trái!")
        base64_img = encode_image_to_base64(image_path)
        client = openai.OpenAI(api_key=st.session_state.openai_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_text},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}
                        }
                    ]
                }
            ],
            max_tokens=1000
        )
        return response.choices[0].message.content
    else:
        raise Exception("Mô hình AI không hợp lệ.")

def get_decimal_from_dms(dms, ref):
    try:
        degrees = dms[0]
        minutes = dms[1]
        seconds = dms[2]
        dec = float(degrees) + float(minutes)/60 + float(seconds)/3600
        if ref in ['S', 'W']: dec = -dec
        return dec
    except:
        return 0.0

def extract_exif_data(image_path):
    try:
        image = ImageOps.exif_transpose(Image.open(image_path))
    except: return "Không rõ", "Không rõ"
    
    exif_time = "Không có dữ liệu thời gian"
    location_text = "Không có GPS - Vị trí ước lượng bởi AI"
    try:
        exif = image._getexif()
        if exif:
            gps_info = {}
            for key, value in exif.items():
                decoded = TAGS.get(key, key)
                if decoded == "DateTimeOriginal":
                    exif_time = value
                elif decoded == "GPSInfo":
                    for t in value:
                        sub_tag = GPSTAGS.get(t, t)
                        gps_info[sub_tag] = value[t]
            
            if 'GPSLatitude' in gps_info and 'GPSLongitude' in gps_info:
                lat = get_decimal_from_dms(gps_info['GPSLatitude'], gps_info['GPSLatitudeRef'])
                lon = get_decimal_from_dms(gps_info['GPSLongitude'], gps_info['GPSLongitudeRef'])
                if lat != 0.0 and lon != 0.0:
                    try:
                        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=16"
                        headers = {'User-Agent': 'TravelAIApp/1.0'}
                        r = requests.get(url, headers=headers, timeout=3).json()
                        address = r.get('display_name', "")
                        if address:
                            location_text = f"{address} (📍 {lat:.4f}, {lon:.4f})"
                        else:
                            location_text = f"📍 Tọa độ: {lat:.4f}, {lon:.4f}"
                    except:
                        location_text = f"📍 Tọa độ: {lat:.4f}, {lon:.4f}"
    except: pass
    return exif_time, location_text

def make_aspect_ratio_image(image_path, target_ratio):
    image = ImageOps.exif_transpose(Image.open(image_path))
    w, h = image.size
    if target_ratio == "4:5":
        target_w, target_h = 1080, 1350
    elif target_ratio == "1:1":
        target_w, target_h = 1080, 1080
    else: return image

    bg = image.resize((target_w, target_h)).filter(ImageFilter.GaussianBlur(15))
    img_ratio = w / h
    target_aspect = target_w / target_h

    if img_ratio > target_aspect:
        new_w = target_w
        new_h = int(target_w / img_ratio)
    else:
        new_h = target_h
        new_w = int(target_h * img_ratio)

    resized_img = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    offset = ((target_w - new_w) // 2, (target_h - new_h) // 2)
    bg.paste(resized_img, offset)
    return bg

# ==========================================
# 4. QUẢN LÝ TRẠNG THÁI GIAO DIỆN
# ==========================================
if 'active_post_id' not in st.session_state:
    st.session_state.active_post_id = None
if 'pending_post' not in st.session_state:
    st.session_state.pending_post = None
if 'last_uploaded_hash' not in st.session_state:
    st.session_state.last_uploaded_hash = None

def get_post(post_id):
    conn = sqlite3.connect("travel_ai.db")
    c = conn.cursor()
    c.execute("SELECT * FROM posts WHERE id=?", (post_id,))
    row = c.fetchone()
    conn.close()
    return row

def delete_post(post_id, image_path):
    if os.path.exists(image_path):
        try: os.remove(image_path)
        except: pass
    conn = sqlite3.connect("travel_ai.db")
    c = conn.cursor()
    c.execute("DELETE FROM posts WHERE id=?", (post_id,))
    conn.commit()
    conn.close()
    if st.session_state.active_post_id == post_id:
        st.session_state.active_post_id = None
    st.rerun()

# ==========================================
# 5. KHU VỰC TÙY CHỈNH PROMPT
# ==========================================
with st.expander("📝 Tùy chỉnh Master Prompt", expanded=False):
    st.session_state.custom_prompt = st.text_area(
        "Nội dung yêu cầu (Prompt) gửi tới AI:",
        value=st.session_state.custom_prompt,
        height=450
    )
    if st.button("🔄 Khôi phục phôi mặc định"):
        st.session_state.custom_prompt = DEFAULT_PROMPT
        st.rerun()

active_prompt = st.session_state.custom_prompt

# ==========================================
# 6. KHU VỰC TẢI ẢNH (TOP)
# ==========================================
uploaded_file = st.file_uploader("Kéo thả ảnh mới vào đây (Tối đa 3MB)", type=["jpg", "jpeg", "png"])

if uploaded_file:
    file_bytes = uploaded_file.getvalue()
    file_hash = hashlib.md5(file_bytes).hexdigest()
    
    existing_post = get_post(file_hash)
    
    if existing_post:
        if st.session_state.active_post_id != file_hash:
            st.session_state.active_post_id = file_hash
            st.session_state.pending_post = None
            st.session_state.last_uploaded_hash = file_hash
            st.rerun()
    else:
        if st.session_state.last_uploaded_hash != file_hash:
            file_ext = uploaded_file.name.split('.')[-1]
            pending_img_path = os.path.join(UPLOAD_DIR, f"pending_{file_hash}.{file_ext}")
            
            with open(pending_img_path, "wb") as f:
                f.write(file_bytes)
                
            exif_time, loc_text = extract_exif_data(pending_img_path)
            
            st.session_state.pending_post = {
                "id": file_hash,
                "img_path": pending_img_path,
                "exif_time": exif_time,
                "loc_text": loc_text,
                "ext": file_ext
            }
            st.session_state.active_post_id = None
            st.session_state.last_uploaded_hash = file_hash
            st.rerun()

# --- Hiển thị 1: Trạng thái chờ phân tích (Pending) ---
if st.session_state.pending_post:
    p = st.session_state.pending_post
    col_img, col_content = st.columns([1, 1.2])
    
    with col_img:
        st.image(p["img_path"], caption="Ảnh đang chờ xử lý", use_container_width=True)
        st.info(f"📅 **Thời gian:** {p['exif_time']}\n\n📍 **Địa điểm:** {p['loc_text']}")
        st.write("---")
        c1, c2 = st.columns(2)
        with c1: st.image(make_aspect_ratio_image(p["img_path"], "4:5"), caption="Tỷ lệ 4:5 (Dọc)")
        with c2: st.image(make_aspect_ratio_image(p["img_path"], "1:1"), caption="Tỷ lệ 1:1 (Vuông)")
        
    with col_content:
        st.warning("⚠️ Ảnh này chưa được phân tích và chưa lưu vào thư viện.")
        
        selected_ai = st.radio("🤖 Chọn mô hình AI phân tích:", ["Google Gemini", "ChatGPT (OpenAI)"], horizontal=True)
        
        if st.button("🚀 Bấm để AI phân tích ảnh này", type="primary", use_container_width=True):
            with st.spinner(f"Đang phân tích bằng {selected_ai}..."):
                try:
                    final_prompt = f"Thông tin phụ: Ảnh chụp lúc {p['exif_time']}, tại {p['loc_text']}.\n\n{active_prompt}"
                    raw_res = analyze_image_with_ai(selected_ai, final_prompt, p["img_path"])
                    
                    res_text = raw_res.split("---")
                    c_kids, c_mkt = "", ""
                    for i in range(len(res_text)):
                        if "KIDSLAND" in res_text[i]: c_kids = res_text[i+1].strip()
                        elif "MARKETING" in res_text[i]: c_mkt = res_text[i+1].strip()
                    
                    final_img_path = os.path.join(UPLOAD_DIR, f"{p['id']}.{p['ext']}")
                    if os.path.exists(p["img_path"]):
                        shutil.move(p["img_path"], final_img_path)
                    
                    conn = sqlite3.connect("travel_ai.db")
                    conn.execute("INSERT OR IGNORE INTO posts VALUES (?, ?, ?, ?, ?, ?, ?)", 
                                 (p["id"], final_img_path, p["exif_time"], p["loc_text"], 
                                  c_kids, c_mkt, datetime.datetime.now()))
                    conn.commit()
                    conn.close()
                    
                    st.session_state.active_post_id = p["id"]
                    st.session_state.pending_post = None
                    st.rerun()
                except Exception as e:
                    st.error(f"Lỗi: {e}")

# --- Hiển thị 2: Xem ảnh đã lưu trong thư viện (Active) ---
elif st.session_state.active_post_id:
    post = get_post(st.session_state.active_post_id)
    if post:
        p_id, p_img, p_time, p_loc, p_kids, p_mkt, p_created = post
        
        col_img, col_content = st.columns([1, 1.2])
        with col_img:
            st.image(p_img, caption="Ảnh trong thư viện", use_container_width=True)
            st.info(f"📅 **Thời gian:** {p_time}\n\n📍 **Địa điểm:** {p_loc}")
            st.write("---")
            c1, c2 = st.columns(2)
            with c1: st.image(make_aspect_ratio_image(p_img, "4:5"), caption="Tỷ lệ 4:5 (Dọc)")
            with c2: st.image(make_aspect_ratio_image(p_img, "1:1"), caption="Tỷ lệ 1:1 (Vuông)")
            
        with col_content:
            st.success("✅ Đã phân tích xong!")
            tab1, tab2 = st.tabs(["🏫 Kidsland", "🎯 Marketing"])
            
            with tab1:
                st.text_area("Nội dung Kidsland:", value=p_kids, height=250, key=f"kids_{p_id}")
                ai_re_kids = st.radio("Mô hình AI viết lại:", ["Google Gemini", "ChatGPT (OpenAI)"], key=f"radio_k_{p_id}", horizontal=True)
                if st.button("🔄 Viết lại bài Kidsland", key=f"re_kids_{p_id}"):
                    with st.spinner(f"Đang viết lại bằng {ai_re_kids}..."):
                        try:
                            re_prompt = f"Thông tin: Ảnh chụp {p_time} tại {p_loc}.\n\nYêu cầu: Viết lại theo đúng quy tắc phần ---KIDSLAND--- trong Master Prompt:\n{active_prompt}"
                            raw_res = analyze_image_with_ai(ai_re_kids, re_prompt, p_img)
                            clean_text = raw_res.replace("---KIDSLAND---", "").replace("---MARKETING---", "").strip()
                            
                            conn = sqlite3.connect("travel_ai.db")
                            conn.execute("UPDATE posts SET content_kidsland=? WHERE id=?", (clean_text, p_id))
                            conn.commit()
                            conn.close()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Lỗi: {e}")

            with tab2:
                st.text_area("Nội dung Marketing:", value=p_mkt, height=250, key=f"mkt_{p_id}")
                ai_re_mkt = st.radio("Mô hình AI viết lại:", ["Google Gemini", "ChatGPT (OpenAI)"], key=f"radio_m_{p_id}", horizontal=True)
                if st.button("🔄 Viết lại bài Marketing", key=f"re_mkt_{p_id}"):
                    with st.spinner(f"Đang viết lại bằng {ai_re_mkt}..."):
                        try:
                            re_prompt = f"Thông tin: Ảnh chụp {p_time} tại {p_loc}.\n\nYêu cầu: Viết lại theo đúng quy tắc phần ---MARKETING--- trong Master Prompt:\n{active_prompt}"
                            raw_res = analyze_image_with_ai(ai_re_mkt, re_prompt, p_img)
                            clean_text = raw_res.replace("---KIDSLAND---", "").replace("---MARKETING---", "").strip()
                            
                            conn = sqlite3.connect("travel_ai.db")
                            conn.execute("UPDATE posts SET content_marketing=? WHERE id=?", (clean_text, p_id))
                            conn.commit()
                            conn.close()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Lỗi: {e}")

# ==========================================
# 7. KHU VỰC THƯ VIỆN ẢNH (BOTTOM)
# ==========================================
st.divider()
st.subheader("📚 Thư viện đã xử lý (Lưu trữ 30 ngày)")

conn = sqlite3.connect("travel_ai.db")
c = conn.cursor()
c.execute("SELECT id, image_path, created_at FROM posts ORDER BY created_at DESC")
all_posts = c.fetchall()
conn.close()

if not all_posts:
    st.info("Chưa có bức ảnh nào được phân tích và lưu vào thư viện.")
else:
    cols = st.columns(5)
    for index, record in enumerate(all_posts):
        r_id, r_img, r_date = record
        col = cols[index % 5]
        with col:
            st.image(r_img, use_container_width=True)
            
            btn_col1, btn_col2 = st.columns([1, 1])
            with btn_col1:
                if st.button("👁️ Xem", key=f"view_{r_id}", use_container_width=True):
                    st.session_state.active_post_id = r_id
                    st.session_state.pending_post = None
                    st.rerun()
            with btn_col2:
                if st.button("🗑️ Xóa", key=f"del_{r_id}", use_container_width=True):
                    delete_post(r_id, r_img)
