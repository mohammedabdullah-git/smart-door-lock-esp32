import os
import uuid
import requests
import time
import random

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from face_engine import FaceEngine

from db import (
    get_access_logs,
    update_user
)


# ============================================================
# ESP32-CAM CONFIG
# ============================================================

# IP ESP32-CAM thật của bạn
ESP32_IP = "10.107.164.210"

# ESP32-CAM endpoints
ESP32_BASE_URL = f"http://{ESP32_IP}"
ESP32_CAPTURE_URL = f"http://{ESP32_IP}/capture"
ESP32_STREAM_URL = f"http://{ESP32_IP}:81/stream"

# ĐÃ CÓ RELAY + Ổ KHÓA
# FastAPI chỉ gọi endpoint này khi AI nhận diện ACCEPT
ESP32_UNLOCK_URL = f"http://{ESP32_IP}/unlock"

# Endpoint command chỉ để test thủ công, không dùng cho REJECT nữa
ESP32_COMMAND_URL = f"http://{ESP32_IP}/command"


# ============================================================
# UNLOCK COOLDOWN CONFIG
# ============================================================

# Tránh việc user đứng trước camera lâu làm FastAPI gửi /unlock liên tục
UNLOCK_COOLDOWN_SECONDS = 8
last_unlock_time = 0




# ============================================================
# AUTO CHALLENGE-RESPONSE CONFIG
# ============================================================

# FEATURE FLAGS
# False: tạm tắt challenge-response vì LOOK_CENTER chưa ổn định trên ESP32-CAM.
# True : bật lại luồng random challenge-response.
ENABLE_CHALLENGE_RESPONSE = False

# user.html sẽ gọi /auto-verify-from-esp32 mỗi 2 giây.
AUTO_VERIFY_INTERVAL_SECONDS = 2

# Nếu user không thực hiện đúng challenge trong thời gian này thì reset.
CHALLENGE_TIMEOUT_SECONDS = 12

# Sau khi mở khóa thành công, tạm dừng challenge một khoảng ngắn để tránh mở liên tục.
SUCCESS_PAUSE_SECONDS = 8

CHALLENGES = [
    {
        "code": "LOOK_LEFT",
        "text": "Vui lòng quay mặt sang trái"
    },
    {
        "code": "LOOK_RIGHT",
        "text": "Vui lòng quay mặt sang phải"
    }
]

challenge_state = {
    "active": False,
    "challenge_code": None,
    "challenge_text": None,
    "created_at": 0,
    "challenge_passed": False,
    "passed_at": 0,
    "last_success_time": 0
}


# ============================================================
# PATH CONFIG
# ============================================================

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(CURRENT_DIR, "uploaded")

os.makedirs(UPLOAD_DIR, exist_ok=True)


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="Smart Door Face Recognition AI Server",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = FaceEngine()


# ============================================================
# UTILS
# ============================================================

def save_upload_file(upload_file: UploadFile) -> str:
    ext = os.path.splitext(upload_file.filename)[1]

    if ext == "":
        ext = ".jpg"

    filename = f"{uuid.uuid4().hex}{ext}"
    save_path = os.path.join(UPLOAD_DIR, filename)

    with open(save_path, "wb") as f:
        f.write(upload_file.file.read())

    return save_path


def capture_from_esp32() -> str:
    try:
        response = requests.get(
            ESP32_CAPTURE_URL,
            timeout=8
        )

        response.raise_for_status()

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Cannot capture image from ESP32-CAM: {str(e)}"
        )

    content_type = response.headers.get("content-type", "")

    if "image" not in content_type.lower():
        raise HTTPException(
            status_code=500,
            detail=f"ESP32 /capture did not return image. Content-Type: {content_type}"
        )

    filename = f"esp32_capture_{uuid.uuid4().hex}.jpg"
    save_path = os.path.join(UPLOAD_DIR, filename)

    with open(save_path, "wb") as f:
        f.write(response.content)

    return save_path


def send_unlock_command():
    global last_unlock_time

    now = time.time()

    if now - last_unlock_time < UNLOCK_COOLDOWN_SECONDS:
        remaining = UNLOCK_COOLDOWN_SECONDS - (now - last_unlock_time)

        return {
            "sent": False,
            "mode": "COOLDOWN",
            "message": f"Unlock recently sent. Please wait {remaining:.1f} seconds.",
            "cooldown_seconds": UNLOCK_COOLDOWN_SECONDS
        }

    try:
        response = requests.get(
            ESP32_UNLOCK_URL,
            timeout=5
        )

        response.raise_for_status()

        last_unlock_time = now

        try:
            esp32_response = response.json()
        except Exception:
            esp32_response = response.text

        return {
            "sent": True,
            "mode": "REAL",
            "message": "Unlock command sent to ESP32.",
            "unlock_url": ESP32_UNLOCK_URL,
            "esp32_response": esp32_response
        }

    except Exception as e:
        return {
            "sent": False,
            "mode": "REAL",
            "message": f"Failed to send unlock command: {str(e)}",
            "unlock_url": ESP32_UNLOCK_URL
        }


def send_command_to_esp32(msg: str):
    try:
        response = requests.get(
            ESP32_COMMAND_URL,
            params={"msg": msg},
            timeout=5
        )

        response.raise_for_status()

        try:
            esp32_response = response.json()
        except Exception:
            esp32_response = response.text

        return {
            "sent": True,
            "message": "Command sent to ESP32-CAM.",
            "esp32_url": ESP32_COMMAND_URL,
            "sent_msg": msg,
            "esp32_response": esp32_response
        }

    except Exception as e:
        return {
            "sent": False,
            "message": f"Cannot send command to ESP32-CAM: {str(e)}"
        }


def reset_challenge():
    challenge_state["active"] = False
    challenge_state["challenge_code"] = None
    challenge_state["challenge_text"] = None
    challenge_state["created_at"] = 0
    challenge_state["challenge_passed"] = False
    challenge_state["passed_at"] = 0


def create_random_challenge():
    selected = random.choice(CHALLENGES)

    challenge_state["active"] = True
    challenge_state["challenge_code"] = selected["code"]
    challenge_state["challenge_text"] = selected["text"]
    challenge_state["created_at"] = time.time()
    challenge_state["challenge_passed"] = False
    challenge_state["passed_at"] = 0

    return selected


# ============================================================
# BASIC ROUTES
# ============================================================

@app.get("/")
def root():
    return {
        "success": True,
        "message": "Smart Door Face Recognition AI Server is running.",
        "esp32_ip": ESP32_IP,
        "esp32_capture_url": ESP32_CAPTURE_URL,
        "esp32_stream_url": ESP32_STREAM_URL,
        "esp32_unlock_url": ESP32_UNLOCK_URL,
        "esp32_command_url": ESP32_COMMAND_URL
    }


@app.get("/config")
def get_config():
    return {
        "success": True,
        "esp32_ip": ESP32_IP,
        "stream_url": ESP32_STREAM_URL,
        "capture_url": ESP32_CAPTURE_URL,
        "unlock_url": ESP32_UNLOCK_URL,
        "command_url": ESP32_COMMAND_URL
    }


@app.get("/health")
def health():
    return {
        "success": True,
        "message": "AI server OK"
    }


@app.get("/favicon.ico")
def favicon():
    return {}


# ============================================================
# ESP32-CAM ROUTES
# ============================================================

@app.get("/esp32/check")
def check_esp32():
    try:
        response = requests.get(
            ESP32_CAPTURE_URL,
            timeout=5
        )

        return {
            "success": response.ok,
            "capture_url": ESP32_CAPTURE_URL,
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type", "")
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"ESP32-CAM check failed: {str(e)}"
        )


@app.get("/esp32/status")
def esp32_status():
    try:
        response = requests.get(
            f"{ESP32_BASE_URL}/status",
            timeout=5
        )

        response.raise_for_status()

        try:
            esp32_response = response.json()
        except Exception:
            esp32_response = response.text

        return {
            "success": True,
            "esp32_response": esp32_response
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Cannot get ESP32 status: {str(e)}"
        )


@app.get("/esp32/unlock")
def esp32_unlock_manual():
    result = send_unlock_command()

    if result["sent"] is False and result["mode"] != "COOLDOWN":
        raise HTTPException(
            status_code=500,
            detail=result["message"]
        )

    return {
        "success": True,
        **result
    }


@app.get("/esp32/send-command")
def esp32_send_command(msg: str = "HelloESP32"):
    result = send_command_to_esp32(msg)

    if result["sent"] is False:
        raise HTTPException(
            status_code=500,
            detail=result["message"]
        )

    return {
        "success": True,
        **result
    }


# ============================================================
# USER MANAGEMENT ROUTES
# ============================================================

@app.get("/users")
def list_users():
    return {
        "success": True,
        "users": engine.list_users()
    }


@app.put("/users/{user_id}")
def update_user_api(
    user_id: str,
    name: str = Form(...)
):
    try:
        update_user(
            user_id=user_id,
            new_name=name
        )

        return {
            "success": True,
            "message": "User updated successfully.",
            "user_id": user_id,
            "name": name
        }

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )


@app.delete("/users/{user_id}")
def delete_user(user_id: str):
    try:
        return engine.delete_user(user_id)

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )


# ============================================================
# ACCESS LOG ROUTES
# ============================================================

@app.get("/access-logs")
def access_logs(limit: int = 30):
    try:
        return {
            "success": True,
            "logs": get_access_logs(limit=limit)
        }

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )


# ============================================================
# UPLOAD IMAGE ROUTES
# dùng để test bằng ảnh trên máy tính
# ============================================================

@app.post("/register")
def register_user(
    user_id: str = Form(...),
    name: str = Form(...),
    image: UploadFile = File(...)
):
    try:
        image_path = save_upload_file(image)

        result = engine.register_user(
            user_id=user_id,
            name=name,
            image_path=image_path
        )

        return result

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )


@app.post("/recognize")
def recognize_user(
    image: UploadFile = File(...)
):
    try:
        image_path = save_upload_file(image)

        result = engine.recognize(
            image_path=image_path
        )

        if result["access"] is True:
            result["unlock"] = send_unlock_command()
        else:
            result["unlock"] = {
                "sent": False,
                "message": "Not ACCEPT. No command sent to ESP32-CAM."
            }

        result["esp32_command"] = {
            "sent": False,
            "message": "Command endpoint is not used for lock control."
        }

        return result

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )


# ============================================================
# REAL ESP32-CAM ROUTES
# dùng cho web_dashboard thật
# ============================================================

@app.post("/register-from-esp32")
def register_from_esp32(
    user_id: str = Form(...),
    name: str = Form(...)
):
    try:
        image_path = capture_from_esp32()

        result = engine.register_user(
            user_id=user_id,
            name=name,
            image_path=image_path
        )

        result["capture_source"] = "ESP32-CAM"
        result["capture_url"] = ESP32_CAPTURE_URL

        return result

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )


@app.post("/recognize-from-esp32")
def recognize_from_esp32():
    try:
        image_path = capture_from_esp32()

        result = engine.recognize(
            image_path=image_path
        )

        result["capture_source"] = "ESP32-CAM"
        result["capture_url"] = ESP32_CAPTURE_URL

        # Quan trọng:
        # ACCEPT mới gửi /unlock xuống ESP32.
        # REJECT và LOW_CONFIDENCE_RETRY không gửi gì để tránh spam ESP32.
        if result["access"] is True:
            result["unlock"] = send_unlock_command()
        else:
            result["unlock"] = {
                "sent": False,
                "message": "Not ACCEPT. No command sent to ESP32-CAM."
            }

        result["esp32_command"] = {
            "sent": False,
            "message": "Only ACCEPT sends /unlock. REJECT and LOW_CONFIDENCE send nothing."
        }

        return result

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )


@app.post("/auto-verify-from-esp32")
def auto_verify_from_esp32():
    """
    Luồng tự động challenge-response đã tối ưu:
    1. user.html gọi endpoint này mỗi 2 giây.
    2. FastAPI chụp ảnh từ ESP32-CAM.
    3. Nếu chưa thấy mặt: yêu cầu đưa mặt vào camera.
    4. Nếu thấy mặt và chưa có challenge: tạo challenge quay trái/phải.
    5. Nếu đã có challenge: kiểm tra người dùng quay đúng trái/phải chưa.
    6. Nếu challenge đúng: KHÔNG nhận diện ngay bằng ảnh quay mặt.
       Hệ thống chuyển sang CHALLENGE_PASSED_WAIT_CENTER.
    7. Khi người dùng nhìn thẳng lại LOOK_CENTER: lấy frame nhìn thẳng đó để ArcFace recognition.
    8. Nếu ACCEPT: gửi /unlock xuống ESP32-CAM để mở relay.
    """

    now = time.time()

        # ========================================================
    # CHALLENGE-RESPONSE DISABLED MODE
    # ========================================================
    # Khi ENABLE_CHALLENGE_RESPONSE = False:
    # - Không kiểm tra quay trái/phải/nhìn thẳng.
    # - Nhận diện trực tiếp từ ảnh ESP32-CAM.
    # - ACCEPT mới gửi /unlock.
    # - REJECT / LOW_CONFIDENCE không gửi gì xuống ESP32.
    #
    # Phần challenge-response vẫn được giữ lại bên dưới như một chức năng
    # thử nghiệm/mở rộng để trình bày trong báo cáo.
    # ========================================================

    if ENABLE_CHALLENGE_RESPONSE is False:
        try:
            image_path = capture_from_esp32()

            result = engine.recognize(
                image_path=image_path
            )

            result["capture_source"] = "ESP32-CAM"
            result["capture_url"] = ESP32_CAPTURE_URL

            if result["access"] is True:
                unlock_result = send_unlock_command()
            else:
                unlock_result = {
                    "sent": False,
                    "message": "Not ACCEPT. No command sent to ESP32-CAM."
                }

            return {
                "success": True,
                "stage": "RECOGNITION_DONE",
                "message": "Challenge-response is disabled. Direct recognition mode is used.",
                "challenge_enabled": False,
                "recognition": result,
                "unlock": unlock_result
            }

        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=str(e)
            )

    if now - challenge_state["last_success_time"] < SUCCESS_PAUSE_SECONDS:
        remaining = SUCCESS_PAUSE_SECONDS - (now - challenge_state["last_success_time"])

        return {
            "success": True,
            "stage": "SUCCESS_PAUSE",
            "message": f"Đã mở khóa. Vui lòng đợi {remaining:.1f} giây.",
            "challenge": None,
            "direction": None,
            "recognition": None,
            "unlock": {
                "sent": False,
                "message": "System is in success pause."
            }
        }

    try:
        image_path = capture_from_esp32()

        try:
            direction_result = engine.get_face_direction_from_image_path(
                image_path=image_path
            )

        except Exception:
            # Không reset challenge ngay khi mất mặt 1 frame.
            # ESP32-CAM vừa stream vừa capture nên thỉnh thoảng có frame mờ/không thấy mặt.
            # Nếu reset ngay, hệ thống sẽ quay về "đưa mặt vào camera" trước khi kịp recognition.
            if challenge_state["active"] is True:
                elapsed = now - challenge_state["created_at"]

                if elapsed > CHALLENGE_TIMEOUT_SECONDS:
                    reset_challenge()

                    return {
                        "success": True,
                        "stage": "CHALLENGE_TIMEOUT",
                        "message": "Hết thời gian xác thực. Vui lòng thử lại.",
                        "challenge": None,
                        "direction": None,
                        "recognition": None,
                        "unlock": {
                            "sent": False,
                            "message": "Challenge timeout. No command sent to ESP32."
                        }
                    }

                if challenge_state["challenge_passed"] is True:
                    return {
                        "success": True,
                        "stage": "NO_FACE_KEEP_CHALLENGE",
                        "message": "Challenge đã đúng. Vui lòng đưa mặt nhìn thẳng lại camera.",
                        "challenge": {
                            "code": challenge_state["challenge_code"],
                            "text": challenge_state["challenge_text"],
                            "passed": True
                        },
                        "direction": None,
                        "recognition": None,
                        "unlock": {
                            "sent": False,
                            "message": "Face temporarily lost. Keep challenge state and wait for LOOK_CENTER."
                        }
                    }

                return {
                    "success": True,
                    "stage": "NO_FACE_KEEP_CHALLENGE",
                    "message": challenge_state["challenge_text"] + ". Vui lòng giữ khuôn mặt trong camera.",
                    "challenge": {
                        "code": challenge_state["challenge_code"],
                        "text": challenge_state["challenge_text"],
                        "passed": False
                    },
                    "direction": None,
                    "recognition": None,
                    "unlock": {
                        "sent": False,
                        "message": "Face temporarily lost. Keep challenge state."
                    }
                }

            return {
                "success": True,
                "stage": "NO_FACE",
                "message": "Vui lòng đưa khuôn mặt vào camera.",
                "challenge": None,
                "direction": None,
                "recognition": None,
                "unlock": {
                    "sent": False,
                    "message": "No face detected. No command sent to ESP32."
                }
            }

        current_direction = direction_result["direction"]

        # 1. Có mặt nhưng chưa có challenge -> tạo challenge mới.
        if challenge_state["active"] is False:
            selected = create_random_challenge()

            return {
                "success": True,
                "stage": "CHALLENGE_CREATED",
                "message": selected["text"],
                "challenge": {
                    "code": selected["code"],
                    "text": selected["text"],
                    "passed": False
                },
                "direction": current_direction,
                "face_info": direction_result["face_info"],
                "recognition": None,
                "unlock": {
                    "sent": False,
                    "message": "Challenge created. Waiting for user response."
                }
            }

        elapsed = now - challenge_state["created_at"]

        if elapsed > CHALLENGE_TIMEOUT_SECONDS:
            reset_challenge()

            return {
                "success": True,
                "stage": "CHALLENGE_TIMEOUT",
                "message": "Hết thời gian xác thực. Vui lòng thử lại.",
                "challenge": None,
                "direction": current_direction,
                "face_info": direction_result["face_info"],
                "recognition": None,
                "unlock": {
                    "sent": False,
                    "message": "Challenge timeout. No command sent to ESP32."
                }
            }

        expected_direction = challenge_state["challenge_code"]

        # 2. Challenge chưa đạt -> đợi user quay đúng trái/phải.
        if challenge_state["challenge_passed"] is False:
            if current_direction != expected_direction:
                return {
                    "success": True,
                    "stage": "CHALLENGE_WAITING",
                    "message": challenge_state["challenge_text"],
                    "challenge": {
                        "code": challenge_state["challenge_code"],
                        "text": challenge_state["challenge_text"],
                        "passed": False
                    },
                    "direction": current_direction,
                    "face_info": direction_result["face_info"],
                    "recognition": None,
                    "unlock": {
                        "sent": False,
                        "message": "Challenge not passed yet."
                    }
                }

            # Đã quay đúng challenge, nhưng chưa nhận diện ngay.
            # Chuyển sang bước yêu cầu nhìn thẳng lại để lấy frame đẹp hơn cho ArcFace.
            challenge_state["challenge_passed"] = True
            challenge_state["passed_at"] = now

            return {
                "success": True,
                "stage": "CHALLENGE_PASSED_WAIT_CENTER",
                "message": "Challenge đúng. Vui lòng nhìn thẳng vào camera để nhận diện.",
                "challenge": {
                    "code": challenge_state["challenge_code"],
                    "text": challenge_state["challenge_text"],
                    "passed": True,
                    "expected": expected_direction,
                    "actual": current_direction
                },
                "direction": current_direction,
                "face_info": direction_result["face_info"],
                "recognition": None,
                "unlock": {
                    "sent": False,
                    "message": "Challenge passed. Waiting for LOOK_CENTER frame."
                }
            }

        # 3. Challenge đã đạt -> chỉ nhận diện khi user nhìn thẳng lại.
        if current_direction != "LOOK_CENTER":
            return {
                "success": True,
                "stage": "CHALLENGE_PASSED_WAIT_CENTER",
                "message": "Challenge đúng. Vui lòng nhìn thẳng vào camera để nhận diện.",
                "challenge": {
                    "code": challenge_state["challenge_code"],
                    "text": challenge_state["challenge_text"],
                    "passed": True,
                    "expected": expected_direction,
                    "actual": current_direction
                },
                "direction": current_direction,
                "face_info": direction_result["face_info"],
                "recognition": None,
                "unlock": {
                    "sent": False,
                    "message": "Waiting for LOOK_CENTER frame."
                }
            }

        # 4. Đã qua challenge và đã nhìn thẳng -> dùng frame LOOK_CENTER hiện tại để recognition.
        result = engine.recognize(
            image_path=image_path
        )

        reset_challenge()

        if result["access"] is True:
            unlock_result = send_unlock_command()
            challenge_state["last_success_time"] = time.time()
        else:
            unlock_result = {
                "sent": False,
                "message": "Recognition failed. No command sent to ESP32."
            }

        return {
            "success": True,
            "stage": "RECOGNITION_DONE",
            "message": "Challenge passed. LOOK_CENTER frame used for recognition.",
            "challenge": {
                "passed": True,
                "expected": expected_direction,
                "actual": "LOOK_CENTER",
                "recognition_frame": "LOOK_CENTER"
            },
            "direction": current_direction,
            "face_info": direction_result["face_info"],
            "recognition": result,
            "unlock": unlock_result
        }

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
