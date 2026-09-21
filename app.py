import streamlit as st
import google.generativeai as genai
from PIL import Image
from PIL.ExifTags import GPSTAGS, TAGS
import requests
import json
import os

# ---------------------------------------------------------
# 1. QUẢN LÝ API KEY BẰNG FILE JSON (Dùng cho cá nhân)
# ---------------------------------------------------------
CONFIG_FILE = "config.json"

def load_api_key():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                return data.get("api_key", "")
        except:
            return ""
    return ""

def save_api_key(key):
    with open(CONFIG_FILE, "w") as f:
        json.dump({"api_key": key}, f)

# ---------------------------------------------------------
# 2. XỬ LÝ GPS TRONG ẢNH
# ---------------------------------------------------------
def get_decimal_from_dms(dms, ref):
    try:
        degrees = float(dms[0])
        minutes = float(dms[1])
        seconds = float(dms[2])
        dec = degrees + (minutes / 60.0) + (seconds / 3600.0)
        if ref in ["S", "W"]:
            dec = -dec
        return dec
    except Exception:
        return None

def get_gps_info(image):
    try:
        exif = image._getexif()
        if not exif:
            return None, None
        
        gps_info = {}
        for key, value in exif.items():
            decoded = TAGS.get(key, key)
            if decoded == "GPSInfo":
                for t in value:
                    sub_tag = GPSTAGS.get(t, t)
                    gps_info[sub_tag] = value[t]
                    
        if "GPSLatitude" in gps_info and "GPSLongitude" in gps_info:
            lat = get_decimal_from_dms(gps_info["GPSLatitude"], gps_info.get("GPSLatitudeRef", "N"))
            lon = get_decimal_from_dms(gps_info["GPSLongitude"], gps_info.get("GPSLongitudeRef", "E"))
            return lat, lon
        return None, None
    except Exception:
        return None, None

def get_address_from_coords(lat, lon):
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=16"
        headers = {"User-Agent": "MyTravelApp/1.0"}
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return data.get("display_name", "Không thể dịch địa chỉ")
    except Exception:
        return "Lỗi kết nối máy chủ bản đồ"
    return "Không tìm thấy địa chỉ"

# ---------------------------------------------------------
# 3. GIAO DIỆN ỨNG DỤNG STREAMLIT
# ---------------------------------------------------------
st.set_page_config(page_title="AI Photo Check-in", page_icon="📸")

st.title("📸 Trợ lý Viết Bài Tự Động")

# Cột cấu hình API Key
with st.sidebar:
    st.header("⚙️ Cài đặt")
    saved_key = load_api_key()
    api_key_input = st.text_input("Nhập Gemini API Key", type="password", value=saved_key)
    
    if api_key_input != saved_key:
        save_api_key(api_key_input)
        st.success("Đã lưu API Key vào hệ thống!")

if not api_key_input:
    st.warning("Vui lòng nhập Gemini API Key ở menu bên trái để bắt đầu.")
    st.stop()

# Khởi tạo Gemini
genai.configure(api_key=api_key_input)
model = genai.GenerativeModel('gemini-1.5-flash')

uploaded_file = st.file_uploader("Chọn một bức ảnh...", type=["jpg", "jpeg", "png", "heic"])

if uploaded_file is not None:
    img = Image.open(uploaded_file)
    st.image(img, caption="Ảnh bạn đã tải lên", use_container_width=True)
    
    # Rút trích GPS tự động
    lat, lon = get_gps_info(img)
    gps_address = "Không có dữ liệu GPS trong ảnh."
    
    if lat and lon:
        st.success(f"📍 Tọa độ tìm thấy: {lat:.5f}, {lon:.5f}")
        with st.spinner("Đang định vị địa chỉ..."):
            gps_address = get_address_from_coords(lat, lon)
            st.info(f"🏠 Địa chỉ hệ thống: {gps_address}")
    else:
        st.warning("⚠️ Ảnh không có sẵn định vị GPS.")

    # Ô NHẬP GỢI Ý ĐỊA ĐIỂM
    manual_location = st.text_input(
        "✍️ Gợi ý địa điểm cho AI (Không bắt buộc):", 
        placeholder="Ví dụ: Nha Trang, quán cà phê ngã tư, trường Kidsland..."
    )

    if st.button("🚀 Viết Bài Ngay"):
        with st.spinner("AI đang phân tích hình ảnh và thông tin..."):
            try:
                # Trộn cả dữ liệu GPS tự động, Gợi ý của bạn và Dữ liệu hình ảnh vào Prompt
                prompt = f"""
                Bạn là một người sáng tạo nội dung chuyên nghiệp. Hãy phân tích bức ảnh này và viết một bài đăng mạng xã hội.
                
                Dữ liệu địa điểm đầu vào:
                1. GPS trích xuất từ ảnh: {gps_address}
                2. Gợi ý thêm từ tôi: {manual_location if manual_location else 'Không có'}
                
                Yêu cầu:
                - Đối chiếu sự hợp lý giữa 'Gợi ý từ tôi', 'GPS', và các chi tiết thực tế bạn nhìn thấy trong ảnh (biển hiệu, xe cộ, kiến trúc, thời tiết).
                - Xác định địa điểm chính xác nhất có thể.
                - Viết 1 đoạn văn thu hút, tự nhiên kèm emoji để đăng Facebook. Không cần giải thích quá trình bạn phân tích.
                """
                
                response = model.generate_content([prompt, img])
                st.subheader("✨ Gợi ý bài đăng:")
                st.write(response.text)
                
            except Exception as e:
                st.error(f"Đã xảy ra lỗi: {e}")
