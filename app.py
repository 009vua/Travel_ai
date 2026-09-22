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
import json

# ==========================================
# 1. QUẢN LÝ CẤU HÌNH BẰNG CONFIG.JSON
# ==========================================
CONFIG_FILE = "config.json"
DEFAULT_PROMPT = """BẮT BUỘC TRẢ VỀ THEO ĐÚNG ĐỊNH DẠNG:
---KIDSLAND---
Đóng vai hiệu trưởng trường mầm non có 10 năm kinh nghiệm.
Nhiệm vụ: Dựa vào ảnh và thời gian/địa điểm, tìm ra một giá trị giáo dục hoặc bài học cuộc sống.
Kỹ thuật: Áp dụng "Đối lập bối cảnh". So sánh quy luật thông thường của thời gian/địa điểm đó với thực tế trong ảnh (Ví dụ: Giờ đón trẻ thường ồn ào nhưng trong ảnh lại bình yên).
Viết bài Facebook 2-3 dòng, giọng văn tản văn, chiêm nghiệm. Không quảng cáo.
---
---MARKETING---
Đóng vai admin fanpage du lịch có 10 năm kinh nghiệm.
Nhiệm vụ: Phân tích ảnh dưới góc nhìn trải nghiệm. 
Kỹ thuật: Áp dụng "Đối lập bối cảnh" giữa thời gian thực tế và chi tiết trong ảnh (Ví dụ: 17h00 đáng ra kẹt xe nhưng đường lại vắng sau mưa).
Viết bài Facebook 3-5 dòng kể một cảm xúc hoặc câu chuyện. Giọng văn tự nhiên, gợi hình, không quảng cáo lộ liễu."""

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {"gemini_key": "", "openai_key": "", "custom_prompt": DEFAULT_PROMPT}

def save_config(config_data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config_data, f, ensure_ascii=False, indent=4)

config = load_config()

# ==========================================
# 2. KHỞI TẠO HỆ THỐNG & SESSION STATE
# ==========================================
st.set_page_config(page_title="Facebook Content Studio", page_icon="📘", layout="wide")

if 'gemini_key' not in st.session_state: st.session_state.gemini_key = config.get("gemini_key", "")
if 'openai_key' not in st.session_state: st.session_state.openai_key = config.get("openai_key", "")
if 'custom_prompt' not in st.session_state: st.session_state.custom_prompt = config.get("custom_prompt", DEFAULT_PROMPT)

UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR): os.makedirs(UPLOAD_DIR)

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
            try: os.remove(row[0])
            except: pass
    c.execute("DELETE FROM posts WHERE created_at < ?", (thirty_days_ago,))
    conn.commit()
    conn.close()

init_db()

with st.sidebar.expander("⚙️ Cài đặt API Keys", expanded=True):
    new_gemini = st.text_input("Nhập Gemini API Key:", value=st.session_state.gemini_key, type="password")
    new_openai = st.text_input("Nhập ChatGPT API Key:", value=st.session_state.openai_key, type="password")
    
    if st.button("💾 Lưu API Keys"):
        config["gemini_key"] = new_gemini
        config["openai_key"] = new_openai
        save_config(config)
        st.session_state.gemini_key = new_gemini
        st.session_state.openai_key = new_openai
        st.success("Đã lưu vào hệ thống!")

st.title("📘 Facebook AI Content Studio")

# ==========================================
# 3. CÁC HÀM XỬ LÝ ẢNH & GỌI AI
# ==========================================
def encode_image_to_base64(image_path):
    img = ImageOps.exif_transpose(Image.open(image_path))
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode('utf-8')

def analyze_image_with_ai(ai_provider, prompt_text, image_path):
    if ai_provider == "Google Gemini":
        if not st.session_state.gemini_key: raise Exception("Thiếu Gemini API Key!")
        genai.configure(api_key=st.session_state.gemini_key)
        model = genai.GenerativeModel('gemini-3.6-flash')
        correct_img = ImageOps.exif_transpose(Image.open(image_path))
        response = model.generate_content([prompt_text, correct_img])
        return response.text
    elif ai_provider == "ChatGPT (OpenAI)":
        if not st.session_state.openai_key: raise Exception("Thiếu OpenAI API Key!")
        base64_img = encode_image_to_base64(image_path)
        client = openai.OpenAI(api_key=st.session_state.openai_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}
                ]}
            ]
        )
        return response.choices[0].message.content

def get_decimal_from_dms(dms, ref):
    try:
        dec = float(dms[0]) + float(dms[1])/60 + float(dms[2])/3600
        if ref in ['S', 'W']: dec = -dec
        return dec
    except: return 0.0

def extract_exif_data(image_path):
    try: image = ImageOps.exif_transpose(Image.open(image_path))
    except: return "Không rõ", "Không có GPS", False, False
    
    exif_time = "Không có dữ liệu thời gian"
    location_text = "Không có GPS"
    has_gps = False
    has_time = False
    
    try:
        exif = image._getexif()
        if exif:
            gps_info = {}
            for key, value in exif.items():
                decoded = TAGS.get(key, key)
                if decoded == "DateTimeOriginal": 
                    exif_time = value
                    has_time = True
                elif decoded == "GPSInfo":
                    for t in value: gps_info[GPSTAGS.get(t, t)] = value[t]
            
            if 'GPSLatitude' in gps_info and 'GPSLongitude' in gps_info:
                lat = get_decimal_from_dms(gps_info['GPSLatitude'], gps_info.get('GPSLatitudeRef', 'N'))
                lon = get_decimal_from_dms(gps_info['GPSLongitude'], gps_info.get('GPSLongitudeRef', 'E'))
                if lat != 0.0 and lon != 0.0:
                    has_gps = True
                    try:
                        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=16"
                        r = requests.get(url, headers={'User-Agent': 'TravelAIApp/1.0'}, timeout=3).json()
                        address = r.get('display_name', "")
                        location_text = f"{address} (📍 {lat:.4f}, {lon:.4f})" if address else f"📍 Tọa độ: {lat:.4f}, {lon:.4f}"
                    except: location_text = f"📍 Tọa độ: {lat:.4f}, {lon:.4f}"
    except: pass
    return exif_time, location_text, has_gps, has_time

def make_aspect_ratio_image(image_path, target_ratio):
    image = ImageOps.exif_transpose(Image.open(image_path))
    w, h = image.size
    target_w, target_h = (1080, 1350) if target_ratio == "4:5" else (1080, 1080)
    bg = image.resize((target_w, target_h)).filter(ImageFilter.GaussianBlur(15))
    img_ratio = w / h
    target_aspect = target_w / target_h
    if img_ratio > target_aspect:
        new_w, new_h = target_w, int(target_w / img_ratio)
    else:
        new_h, new_w = target_h, int(target_h * img_ratio)
    resized_img = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    bg.paste(resized_img, ((target_w - new_w) // 2, (target_h - new_h) // 2))
    return bg

# ==========================================
# 4. KHU VỰC TÙY CHỈNH PROMPT & UPLOAD
# ==========================================
with st.expander("📝 Tùy chỉnh Master Prompt", expanded=False):
    new_prompt = st.text_area("Nội dung Master Prompt:", value=st.session_state.custom_prompt, height=350)
    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("💾 Lưu Prompt"):
            config["custom_prompt"] = new_prompt
            save_config(config)
            st.session_state.custom_prompt = new_prompt
            st.success("Đã lưu!")
    with col2:
        if st.button("🔄 Khôi phục mặc định"):
            config["custom_prompt"] = DEFAULT_PROMPT
            save_config(config)
            st.session_state.custom_prompt = DEFAULT_PROMPT
            st.rerun()

active_prompt = st.session_state.custom_prompt

if 'active_post_id' not in st.session_state: st.session_state.active_post_id = None
if 'pending_post' not in st.session_state: st.session_state.pending_post = None

def get_post(post_id):
    conn = sqlite3.connect("travel_ai.db")
    c = conn.cursor()
    c.execute("SELECT * FROM posts WHERE id=?", (post_id,))
    row = c.fetchone()
    conn.close()
    return row

uploaded_file = st.file_uploader("Kéo thả ảnh mới vào đây", type=["jpg", "jpeg", "png", "heic"])

if uploaded_file:
    file_bytes = uploaded_file.getvalue()
    file_hash = hashlib.md5(file_bytes).hexdigest()
    
    if get_post(file_hash):
        if st.session_state.active_post_id != file_hash:
            st.session_state.active_post_id = file_hash
            st.session_state.pending_post = None
            st.rerun()
    else:
        file_ext = uploaded_file.name.split('.')[-1]
        pending_img_path = os.path.join(UPLOAD_DIR, f"pending_{file_hash}.{file_ext}")
        with open(pending_img_path, "wb") as f: f.write(file_bytes)
        
        exif_time, loc_text, has_gps, has_time = extract_exif_data(pending_img_path)
        st.session_state.pending_post = {
            "id": file_hash, "img_path": pending_img_path,
            "exif_time": exif_time, "loc_text": loc_text, 
            "has_gps": has_gps, "has_time": has_time, "ext": file_ext
        }
        st.session_state.active_post_id = None

# --- XỬ LÝ ẢNH MỚI ---
if st.session_state.pending_post:
    p = st.session_state.pending_post
    col_img, col_content = st.columns([1, 1.2])
    
    with col_img:
        st.image(p["img_path"], caption="Ảnh đang chờ xử lý", use_container_width=True)
        st.info(f"📅 **Thời gian gốc:** {p['exif_time']}\n\n📍 **Địa điểm gốc:** {p['loc_text']}")
        
    with col_content:
        st.warning("⚠️ Cấu hình dữ liệu trước khi phân tích:")
        
        # 1. KHỐI XỬ LÝ THỜI GIAN
        manual_time = ""
        if p["has_time"]:
            st.success(f"✅ Ảnh CÓ sẵn dữ liệu Thời gian.")
            final_time_text = p['exif_time']
        else:
            st.error("❌ Ảnh KHÔNG CÓ dữ liệu Thời gian.")
            manual_time = st.text_input("✍️ Nhập thời gian chụp (Giúp AI hiểu rõ bối cảnh hơn):", placeholder="VD: 17h00 chiều thứ Sáu, hoặc Sáng sớm 28/4/2026")
            final_time_text = manual_time if manual_time.strip() else "Không rõ thời gian"

        # 2. KHỐI XỬ LÝ ĐỊA ĐIỂM
        manual_loc = ""
        if p["has_gps"]:
            st.success("✅ Ảnh CÓ sẵn dữ liệu GPS.")
            final_loc_text = p['loc_text']
        else:
            st.error("❌ Ảnh KHÔNG CÓ dữ liệu GPS.")
            manual_loc = st.text_input("✍️ Nhập địa điểm của bức ảnh (Bắt buộc để AI không đoán mò):", placeholder="VD: Bãi tắm Hòn Chồng Nha Trang, Trường Kidsland...")
            final_loc_text = manual_loc if manual_loc.strip() else "Không rõ"
            
        selected_ai = st.radio("🤖 Chọn AI:", ["Google Gemini", "ChatGPT (OpenAI)"], horizontal=True)
        
        if st.button("🚀 Bấm để AI phân tích", type="primary", use_container_width=True):
            with st.spinner("Đang xử lý..."):
                try:
                    # Truyền chỉ thị Thời Gian cho AI
                    if p["has_time"]:
                        time_instruction = f"Thời gian (Trích xuất chính xác từ EXIF): {p['exif_time']}."
                    else:
                        time_instruction = f"Thời gian (Do người dùng cung cấp): {manual_time}. Nếu trống, hãy bỏ qua yếu tố thời gian." if manual_time.strip() else "Thời gian: Không xác định."

                    # Truyền chỉ thị Địa Điểm cho AI
                    if p["has_gps"]:
                        loc_instruction = f"Địa điểm (Trích xuất chính xác từ GPS): {p['loc_text']}."
                    else:
                        if manual_loc.strip():
                            loc_instruction = f"Địa điểm (Do người dùng cung cấp): {manual_loc}. Yêu cầu AI: Tuyệt đối sử dụng địa điểm này, KHÔNG SUY ĐOÁN địa điểm khác."
                        else:
                            loc_instruction = "Không có thông tin địa điểm. Yêu cầu AI: Bỏ qua yếu tố địa lý, KHÔNG ĐƯỢC ĐOÁN MÒ địa điểm."

                    final_prompt = f"Thông tin phụ trợ đầu vào:\n- {time_instruction}\n- {loc_instruction}\n\n{active_prompt}"
                    
                    raw_res = analyze_image_with_ai(selected_ai, final_prompt, p["img_path"])
                    
                    c_kids, c_mkt = "", ""
                    res_text = raw_res.split("---")
                    for i in range(len(res_text)):
                        if "KIDSLAND" in res_text[i]: c_kids = res_text[i+1].strip()
                        elif "MARKETING" in res_text[i]: c_mkt = res_text[i+1].strip()
                    
                    final_img_path = os.path.join(UPLOAD_DIR, f"{p['id']}.{p['ext']}")
                    if os.path.exists(p["img_path"]): shutil.move(p["img_path"], final_img_path)
                    
                    # Lưu vào DB với Thời gian và Địa điểm cuối cùng (EXIF hoặc Nhập tay)
                    conn = sqlite3.connect("travel_ai.db")
                    conn.execute("INSERT OR IGNORE INTO posts VALUES (?, ?, ?, ?, ?, ?, ?)", 
                                 (p["id"], final_img_path, final_time_text, final_loc_text, 
                                  c_kids, c_mkt, datetime.datetime.now()))
                    conn.commit()
                    conn.close()
                    
                    st.session_state.active_post_id = p["id"]
                    st.session_state.pending_post = None
                    st.rerun()
                except Exception as e:
                    st.error(f"Lỗi: {e}")

# --- XEM LẠI ẢNH ĐÃ XỬ LÝ ---
elif st.session_state.active_post_id:
    post = get_post(st.session_state.active_post_id)
    if post:
        p_id, p_img, p_time, p_loc, p_kids, p_mkt, p_created = post
        col_img, col_content = st.columns([1, 1.2])
        with col_img:
            st.image(p_img, use_container_width=True)
            st.info(f"📅 **Thời gian:** {p_time}\n\n📍 **Địa điểm:** {p_loc}")
            st.write("---")
            c1, c2 = st.columns(2)
            with c1: st.image(make_aspect_ratio_image(p_img, "4:5"), caption="Tỷ lệ 4:5")
            with c2: st.image(make_aspect_ratio_image(p_img, "1:1"), caption="Tỷ lệ 1:1")
            
        with col_content:
            tab1, tab2 = st.tabs(["🏫 Kidsland", "🎯 Marketing"])
            with tab1:
                st.text_area("Nội dung Kidsland:", value=p_kids, height=250)
            with tab2:
                st.text_area("Nội dung Marketing:", value=p_mkt, height=250)

# ==========================================
# 5. THƯ VIỆN LƯU TRỮ
# ==========================================
st.divider()
st.subheader("📚 Thư viện đã xử lý")
conn = sqlite3.connect("travel_ai.db")
c = conn.cursor()
c.execute("SELECT id, image_path FROM posts ORDER BY created_at DESC")
all_posts = c.fetchall()
conn.close()

if all_posts:
    cols = st.columns(5)
    for index, record in enumerate(all_posts):
        with cols[index % 5]:
            st.image(record[1], use_container_width=True)
            c1, c2 = st.columns(2)
            with c1:
                if st.button("👁️ Xem", key=f"v_{record[0]}"):
                    st.session_state.active_post_id = record[0]
                    st.session_state.pending_post = None
                    st.rerun()
            with c2:
                if st.button("🗑️ Xóa", key=f"d_{record[0]}"):
                    if os.path.exists(record[1]): os.remove(record[1])
                    conn = sqlite3.connect("travel_ai.db")
                    conn.execute("DELETE FROM posts WHERE id=?", (record[0],))
                    conn.commit()
                    conn.close()
                    if st.session_state.active_post_id == record[0]: st.session_state.active_post_id = None
                    st.rerun()
