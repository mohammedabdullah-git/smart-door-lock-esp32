import os
import sys
import cv2
import torch
import numpy as np
import torch.nn.functional as F

from insightface.app import FaceAnalysis
from insightface.utils import face_align

import contextlib
import io
import onnxruntime as ort

from db import (
    create_tables_if_not_exists,
    user_exists,
    create_user,
    save_embedding,
    delete_user as db_delete_user,
    get_all_users,
    get_all_embeddings,
    save_access_log
)


# ============================================================
# Giảm log của ONNXRuntime
# ============================================================

ort.set_default_logger_severity(3)


# ============================================================
# PATH CONFIG
# ============================================================

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

PROJECT_ROOT = os.path.abspath(
    os.path.join(CURRENT_DIR, "..")
)

ARCFACE_TORCH_DIR = os.path.join(
    PROJECT_ROOT,
    "arcface_torch"
)
# Add arcface_torch to Python path before importing custom backbone
if ARCFACE_TORCH_DIR not in sys.path:
    sys.path.append(ARCFACE_TORCH_DIR)

from backbones import get_model


MODEL_PATH = os.path.join(
    PROJECT_ROOT,
    "arcface_torch",
    "work_dirs",
    "1000_phase3_full",
    "last_backbone.pth"
)

UPLOAD_DIR = os.path.join(
    CURRENT_DIR,
    "uploaded"
)

os.makedirs(UPLOAD_DIR, exist_ok=True)


# ============================================================
# THRESHOLD CONFIG
# ============================================================

THRESHOLD_ACCEPT = 0.60
THRESHOLD_RETRY = 0.45


# ============================================================
# FACE ENGINE
# ============================================================

class FaceEngine:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        print("FaceEngine device:", self.device)

        create_tables_if_not_exists()

        self.detector = self._load_scrfd()
        self.recognizer = self._load_arcface_model()

    # --------------------------------------------------------
    # LOAD MODELS
    # --------------------------------------------------------

    def _load_scrfd(self):
        # Chặn log rườm rà từ insightface / onnxruntime khi load model
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            app = FaceAnalysis(
                name="buffalo_l",
                allowed_modules=["detection"],
                providers=[
                    "CUDAExecutionProvider",
                    "CPUExecutionProvider"
                ]
            )

            app.prepare(
                ctx_id=0 if self.device == "cuda" else -1,
                det_size=(640, 640)
            )

        print("SCRFD loaded.")

        return app

    def _load_arcface_model(self):
        model = get_model(
            "r50",
            dropout=0.0,
            fp16=False,
            num_features=512
        ).to(self.device)

        state_dict = torch.load(
            MODEL_PATH,
            map_location="cpu",
            weights_only=True
        )

        clean_state_dict = {}

        for k, v in state_dict.items():
            if k.startswith("module."):
                k = k[7:]
            clean_state_dict[k] = v

        model.load_state_dict(
            clean_state_dict,
            strict=True
        )

        model.eval()

        print("Fine-tuned ArcFace loaded.")

        return model

    # --------------------------------------------------------
    # IMAGE UTILS
    # --------------------------------------------------------

    def read_image(self, image_path):
        image = cv2.imread(image_path)

        if image is None:
            raise ValueError(f"Cannot read image: {image_path}")

        return image

    def detect_largest_face(self, image_bgr):
        faces = self.detector.get(image_bgr)

        if len(faces) == 0:
            return None

        largest_face = max(
            faces,
            key=lambda face: (
                face.bbox[2] - face.bbox[0]
            ) * (
                face.bbox[3] - face.bbox[1]
            )
        )

        return largest_face

    def align_face(self, image_bgr, face):
        aligned_face = face_align.norm_crop(
            image_bgr,
            landmark=face.kps,
            image_size=112
        )

        return aligned_face

    def preprocess_aligned_face(self, aligned_face_bgr):
        img = cv2.cvtColor(
            aligned_face_bgr,
            cv2.COLOR_BGR2RGB
        )

        img = img.astype(np.float32)

        # Normalize giống lúc train: mean = 0.5, std = 0.5
        img = (img / 255.0 - 0.5) / 0.5

        # HWC -> CHW
        img = np.transpose(img, (2, 0, 1))

        tensor = torch.from_numpy(img)
        tensor = tensor.unsqueeze(0).float().to(self.device)

        return tensor

    # --------------------------------------------------------
    # EMBEDDING
    # --------------------------------------------------------

    @torch.no_grad()
    def get_embedding_from_aligned_face(self, aligned_face_bgr):
        face_tensor = self.preprocess_aligned_face(
            aligned_face_bgr
        )

        embedding = self.recognizer(face_tensor)

        embedding = F.normalize(
            embedding,
            p=2,
            dim=1
        )

        return embedding.cpu().numpy()[0]

    def get_embedding_from_image_path(self, image_path, save_aligned=False):
        image_bgr = self.read_image(image_path)

        face = self.detect_largest_face(image_bgr)

        if face is None:
            raise ValueError("No face detected.")

        aligned_face = self.align_face(
            image_bgr,
            face
        )

        aligned_path = None

        if save_aligned:
            filename = os.path.basename(image_path)
            aligned_path = os.path.join(
                UPLOAD_DIR,
                "aligned_" + filename
            )
            cv2.imwrite(aligned_path, aligned_face)

        embedding = self.get_embedding_from_aligned_face(
            aligned_face
        )

        face_info = {
            "bbox": face.bbox.astype(float).tolist(),
            "kps": face.kps.astype(float).tolist(),
            "det_score": float(face.det_score),
            "aligned_path": aligned_path
        }

        return embedding, face_info


    # --------------------------------------------------------
    # FACE DIRECTION / CHALLENGE UTILS
    # --------------------------------------------------------
    # Các hàm dưới đây dùng cho chức năng liveness detection cơ bản
    # bằng random challenge-response.
    #
    # Ý tưởng:
    # - Dựa vào 5 landmark của SCRFD.
    # - Ước lượng hướng mặt: LOOK_LEFT / LOOK_RIGHT / LOOK_CENTER.
    # - Dùng để yêu cầu người dùng quay mặt trái/phải trước khi nhận diện.
    #
    # Trong luồng chạy chính, challenge-response đang tạm tắt vì
    # ESP32-CAM khó nhận diện ổn định trạng thái LOOK_CENTER.

    def estimate_face_direction_from_face(self, face):
        """
        Ước lượng hướng mặt bằng 5 landmark từ SCRFD:
        kps[0] = mắt trái
        kps[1] = mắt phải
        kps[2] = mũi

        Kết quả:
        - LOOK_LEFT
        - LOOK_RIGHT
        - LOOK_CENTER
        - UNKNOWN

        Lưu ý:
        Nếu khi test thực tế thấy trái/phải bị ngược,
        chỉ cần đổi LOOK_LEFT và LOOK_RIGHT ở phần if bên dưới.
        """

        kps = face.kps.astype(np.float32)

        left_eye = kps[0]
        right_eye = kps[1]
        nose = kps[2]

        eye_center_x = (left_eye[0] + right_eye[0]) / 2.0
        eye_distance = abs(right_eye[0] - left_eye[0])

        if eye_distance < 1:
            return {
                "direction": "UNKNOWN",
                "nose_offset_ratio": 0.0
            }

        nose_offset_ratio = (nose[0] - eye_center_x) / eye_distance

        # Ngưỡng này có thể chỉnh sau khi test thực tế.
        # 0.18 nghĩa là mũi lệch khỏi trung tâm hai mắt khoảng 18% khoảng cách hai mắt.
        threshold = 0.18

        if nose_offset_ratio > threshold:
            direction = "LOOK_LEFT"
        elif nose_offset_ratio < -threshold:
            direction = "LOOK_RIGHT"
        else:
            direction = "LOOK_CENTER"

        return {
            "direction": direction,
            "nose_offset_ratio": float(nose_offset_ratio)
        }

    def get_face_direction_from_image_path(self, image_path):
        image_bgr = self.read_image(image_path)

        face = self.detect_largest_face(image_bgr)

        if face is None:
            raise ValueError("No face detected.")

        direction_info = self.estimate_face_direction_from_face(face)

        face_info = {
            "bbox": face.bbox.astype(float).tolist(),
            "kps": face.kps.astype(float).tolist(),
            "det_score": float(face.det_score),
            "direction": direction_info["direction"],
            "nose_offset_ratio": direction_info["nose_offset_ratio"]
        }

        return {
            "success": True,
            "direction": direction_info["direction"],
            "nose_offset_ratio": direction_info["nose_offset_ratio"],
            "face_info": face_info
        }


    def get_embedding_from_bgr(self, image_bgr, save_aligned=False, filename="frame.jpg"):
        face = self.detect_largest_face(image_bgr)

        if face is None:
            raise ValueError("No face detected.")

        aligned_face = self.align_face(
            image_bgr,
            face
        )

        aligned_path = None

        if save_aligned:
            aligned_path = os.path.join(
                UPLOAD_DIR,
                "aligned_" + filename
            )
            cv2.imwrite(aligned_path, aligned_face)

        embedding = self.get_embedding_from_aligned_face(
            aligned_face
        )

        face_info = {
            "bbox": face.bbox.astype(float).tolist(),
            "kps": face.kps.astype(float).tolist(),
            "det_score": float(face.det_score),
            "aligned_path": aligned_path
        }

        return embedding, face_info

    # --------------------------------------------------------
    # COSINE SIMILARITY
    # --------------------------------------------------------

    @staticmethod
    def cosine_similarity(emb1, emb2):
        emb1 = np.asarray(emb1, dtype=np.float32)
        emb2 = np.asarray(emb2, dtype=np.float32)

        emb1 = emb1 / np.linalg.norm(emb1)
        emb2 = emb2 / np.linalg.norm(emb2)

        return float(np.dot(emb1, emb2))

    # --------------------------------------------------------
    # MATCHING
    # --------------------------------------------------------

    def _match_embedding(self, input_embedding):
        embeddings = get_all_embeddings()

        if len(embeddings) == 0:
            raise ValueError("User database is empty.")

        best_user = None
        best_score = -1.0

        for item in embeddings:
            db_embedding = np.array(
                item["embedding"],
                dtype=np.float32
            )

            score = self.cosine_similarity(
                input_embedding,
                db_embedding
            )

            if score > best_score:
                best_score = score
                best_user = item

        if best_score >= THRESHOLD_ACCEPT:
            status = "ACCEPT"
            access = True

        elif best_score >= THRESHOLD_RETRY:
            status = "LOW_CONFIDENCE_RETRY"
            access = False

        else:
            status = "REJECT"
            access = False

        matched_user = None

        if best_user is not None:
            matched_user = {
                "user_id": best_user["user_id"],
                "name": best_user["name"]
            }

        return access, status, best_score, matched_user

    # --------------------------------------------------------
    # REGISTER USER
    # --------------------------------------------------------

    def register_user(self, user_id, name, image_path):
        if user_exists(user_id):
            raise ValueError(f"User ID already exists: {user_id}")

        embedding, face_info = self.get_embedding_from_image_path(
            image_path,
            save_aligned=True
        )

        create_user(
            user_id=user_id,
            name=name
        )

        save_embedding(
            user_id=user_id,
            embedding=embedding.tolist(),
            image_path=image_path
        )

        return {
            "success": True,
            "message": "User registered successfully.",
            "user_id": user_id,
            "name": name,
            "embedding_shape": list(embedding.shape),
            "face_info": face_info
        }

    # --------------------------------------------------------
    # DELETE USER
    # --------------------------------------------------------

    def delete_user(self, user_id):
        db_delete_user(user_id)

        return {
            "success": True,
            "message": "User deleted successfully.",
            "deleted_user": {
                "user_id": user_id
            }
        }

    # --------------------------------------------------------
    # LIST USERS
    # --------------------------------------------------------

    def list_users(self):
        return get_all_users()

    # --------------------------------------------------------
    # RECOGNIZE FROM IMAGE PATH
    # --------------------------------------------------------

    def recognize(self, image_path):
        input_embedding, face_info = self.get_embedding_from_image_path(
            image_path,
            save_aligned=True
        )

        access, status, best_score, matched_user = self._match_embedding(
            input_embedding
        )

        log_user_id = None
        log_name = None

        if matched_user is not None:
            log_user_id = matched_user["user_id"]
            log_name = matched_user["name"]

        save_access_log(
            user_id=log_user_id,
            name=log_name,
            status=status,
            access_granted=access,
            score=best_score,
            image_path=image_path
        )

        return {
            "success": True,
            "access": access,
            "status": status,
            "best_score": best_score,
            "threshold_accept": THRESHOLD_ACCEPT,
            "threshold_retry": THRESHOLD_RETRY,
            "matched_user": matched_user,
            "face_info": face_info
        }

    # --------------------------------------------------------
    # RECOGNIZE FROM BGR FRAME
    # --------------------------------------------------------

    def recognize_from_bgr(self, image_bgr, filename="frame.jpg"):
        input_embedding, face_info = self.get_embedding_from_bgr(
            image_bgr,
            save_aligned=True,
            filename=filename
        )

        access, status, best_score, matched_user = self._match_embedding(
            input_embedding
        )

        log_user_id = None
        log_name = None

        if matched_user is not None:
            log_user_id = matched_user["user_id"]
            log_name = matched_user["name"]

        save_access_log(
            user_id=log_user_id,
            name=log_name,
            status=status,
            access_granted=access,
            score=best_score,
            image_path=face_info.get("aligned_path")
        )

        return {
            "success": True,
            "access": access,
            "status": status,
            "best_score": best_score,
            "threshold_accept": THRESHOLD_ACCEPT,
            "threshold_retry": THRESHOLD_RETRY,
            "matched_user": matched_user,
            "face_info": face_info
        }