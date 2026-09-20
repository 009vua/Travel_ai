import streamlit as st
import google.generativeai as genai
from PIL import Image, ImageFilter
from PIL.ExifTags import TAGS, GPSTAGS
import sqlite3
import os
import datetime
import requests
import hashlib
import shutil

# ==========================================
# 1. KHỞI TẠO HỆ THỐNG & CƠ SỞ DỮ LIỆU
# ==========================================
st.set_page_config(page_title="Facebook Content Studio", page_icon="📘", layout="wide")

UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

def init_db():
    conn = sqlite3.connect("travel_ai.db")
    c = conn.cursor()
    # Dùng id là MD5 Hash để tuyệt đối không bao giờ trùng lặp ảnh
    c.execute('''CREATE TABLE IF NOT EXISTS posts
                 (id TEXT PRIMARY KEY, image_path TEXT,
                  exif_time TEXT, location_text TEXT,
                  content_kidsland TEXT, content_marketing TEXT,
                  created_at DATETIME)''')
    
    # Tự động dọn dẹp ảnh quá 30 ngày
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

# Cài đặt Sidebar
with st.sidebar.expander("⚙️ Cài đặt (Settings)", expanded=False):
    api_key = st.text_input("Nhập Gemini API Key:", type="password")
    st.markdown("[👉 Lấy API Key miễn phí](https://aistudio.google.com/app/apikey)")

st.title("📘 Facebook AI Content Studio")
st.caption("Quản lý nội dung 30 ngày - Không lưu trùng ảnh - Viết bài chuyên sâu")

# ==========================================
# 2. CÁC HÀM XỬ LÝ ẢNH & GPS
# ==========================================
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
        image = Image.open(image_path)
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
    image = Image.open(image_path)
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
# 3. QUẢN LÝ TRẠNG THÁI (SESSION STATE)
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
# 4. KHU VỰC THAO TÁC CHÍNH (TOP)
# ==========================================
DEFAULT_PROMPT = """BẮT BUỘC TRẢ VỀ THEO ĐÚNG ĐỊNH DẠNG:
---KIDSLAND---
Đóng vai hiệu trưởng trường mầm non có 10 năm kinh nghiệm tuyển sinh.

Phân tích bức ảnh dưới góc nhìn giáo dục mầm non.

Không mô tả ảnh đơn thuần.

Hãy tìm một giá trị giáo dục hoặc bài học cuộc sống mà trẻ em có thể học được từ những gì xuất hiện trong ảnh.

Viết bài Facebook từ 5-7 dòng.

Giọng văn chân thành, gần gũi, giàu cảm xúc.

Không quảng cáo lộ liễu.

Không dùng emoji quá nhiều.

Không nhắc đăng ký ngay.

Kết thúc bằng một câu suy ngẫm dành cho phụ huynh.

Mỗi bài phải khai thác một góc nhìn khác nhau để tránh lặp lại nội dung những ngày trước.

Ưu tiên các chủ đề:
- trải nghiệm thực tế
- kỹ năng sống
- sự tự lập
- quan sát thế giới
- tư duy khám phá
- lòng biết ơn
- tình yêu thiên nhiên
- công nghệ và tương lai
- giao thông và cộng đồng
- sự trưởng thành của trẻ

Viết ngắn gọn 5-7 dòng..
---MARKETING---
Mỗi lần viết phải chọn ngẫu nhiên 1 trong 10 góc nhìn:

1. Bình minh
2. Hoàng hôn
3. Nhịp sống địa phương
4. Câu chuyện người dân
5. Trải nghiệm du khách
6. Văn hóa địa phương
7. Ẩm thực gần khu vực
8. Lịch sử nơi chụp
9. Thiên nhiên và khí hậu
10. Góc nhìn nhiếp ảnh

Viết 5-7 dòng.

Không lặp lại góc nhìn của bài trước."""

with st.expander("📝 Tùy chỉnh Master Prompt", expanded=False):
    custom_prompt = st.text_area(
        "Nội dung yêu cầu (Prompt) gửi tới AI:",
        value=DEFAULT_PROMPT,
        height=600
    )

uploaded_file = st.file_uploader("Kéo thả ảnh mới vào đây (Tối đa 3MB)", type=["jpg", "jpeg", "png"])

if uploaded_file:
    file_bytes = uploaded_file.getvalue()
    file_hash = hashlib.md5(file_bytes).hexdigest() # Tạo ID duy nhất bằng mã băm của ảnh
    
    # KHI CÓ ẢNH MỚI: Kiểm tra xem ảnh này đã từng được lưu vào DB chưa?
    existing_post = get_post(file_hash)
    
    if existing_post:
        # Nếu ảnh ĐÃ CÓ trong thư viện -> Không lưu lại, chỉ mở nó lên để xem
        if st.session_state.active_post_id != file_hash:
            st.session_state.active_post_id = file_hash
            st.session_state.pending_post = None
            st.session_state.last_uploaded_hash = file_hash
            st.rerun()
    else:
        # Nếu là ảnh CHƯA TỪNG CÓ -> Đưa vào trạng thái Chờ xử lý (Pending)
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
        if st.button("🚀 Bấm để AI phân tích ảnh này", type="primary", use_container_width=True):
            if not api_key:
                st.error("⚠️ Vui lòng nhập API Key ở thanh bên trái (Sidebar) trước!")
            else:
                with st.spinner("AI đang giải mã vị trí và viết bài..."):
                    try:
                        genai.configure(api_key=api_key)
                        model = genai.GenerativeModel('gemini-3.6-flash')
                        final_prompt = f"Thông tin phụ: Ảnh chụp lúc {p['exif_time']}, tại {p['loc_text']}.\n\n{custom_prompt}"
                        response = model.generate_content([final_prompt, Image.open(p["img_path"])])
                        
                        res_text = response.text.split("---")
                        c_kids, c_mkt = "", ""
                        for i in range(len(res_text)):
                            if "KIDSLAND" in res_text[i]: c_kids = res_text[i+1].strip()
                            elif "MARKETING" in res_text[i]: c_mkt = res_text[i+1].strip()
                        
                        # CHỈ SAU KHI PHÂN TÍCH XONG -> Lưu DB
                        # 1. Đổi tên file từ pending_ sang chính thức
                        final_img_path = os.path.join(UPLOAD_DIR, f"{p['id']}.{p['ext']}")
                        shutil.move(p["img_path"], final_img_path)
                        
                        # 2. Lưu vào DB (Sử dụng INSERT OR IGNORE để chống lỗi lặp)
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
                        st.error(f"Lỗi khi gọi AI: {e}")

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
                if st.button("🔄 Viết lại bài Kidsland", key=f"re_kids_{p_id}"):
                    if not api_key:
                        st.error("⚠️ Vui lòng nhập API Key!")
                    else:
                        with st.spinner("Đang viết lại Kidsland..."):
                            genai.configure(api_key=api_key)
                            model = genai.GenerativeModel('gemini-3.6-flash')
                            # Truyền lại đúng yêu cầu Kidsland từ prompt
                            re_prompt = f"Thông tin: Ảnh chụp {p_time} tại {p_loc}.\nYêu cầu: Viết lại bài Facebook theo đúng quy tắc phần ---KIDSLAND--- (Vai hiệu trưởng 10 năm, rút ra giá trị giáo dục, 5-7 dòng, không quảng cáo, kết bằng câu suy ngẫm, chọn góc nhìn mới tránh lặp lại)."
                            res = model.generate_content([re_prompt, Image.open(p_img)])
                            
                            # Làm sạch text trả về nếu AI vô tình sinh ra tag
                            clean_text = res.text.replace("---KIDSLAND---", "").replace("---MARKETING---", "").strip()
                            
                            conn = sqlite3.connect("travel_ai.db")
                            conn.execute("UPDATE posts SET content_kidsland=? WHERE id=?", (clean_text, p_id))
                            conn.commit()
                            conn.close()
                            st.rerun()

            with tab2:
                st.text_area("Nội dung Marketing:", value=p_mkt, height=250, key=f"mkt_{p_id}")
                if st.button("🔄 Viết lại bài Marketing", key=f"re_mkt_{p_id}"):
                    if not api_key:
                        st.error("⚠️ Vui lòng nhập API Key!")
                    else:
                        with st.spinner("Đang viết lại Marketing..."):
                            genai.configure(api_key=api_key)
                            model = genai.GenerativeModel('gemini-3.6-flash')
                            # Truyền lại đúng yêu cầu Marketing từ prompt
                            re_prompt = f"Thông tin: Ảnh chụp {p_time} tại {p_loc}.\nYêu cầu: Viết lại bài Facebook theo đúng quy tắc phần ---MARKETING--- (5-7 dòng, chọn 1 trong 10 góc nhìn: bình minh, hoàng hôn, văn hóa, ẩm thực, nhiếp ảnh... Góc nhìn phải khác bài trước)."
                            res = model.generate_content([re_prompt, Image.open(p_img)])
                            
                            clean_text = res.text.replace("---KIDSLAND---", "").replace("---MARKETING---", "").strip()
                            
                            conn = sqlite3.connect("travel_ai.db")
                            conn.execute("UPDATE posts SET content_marketing=? WHERE id=?", (clean_text, p_id))
                            conn.commit()
                            conn.close()
                            st.rerun()

# ==========================================
# 5. KHU VỰC THƯ VIỆN ẢNH (BOTTOM)
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