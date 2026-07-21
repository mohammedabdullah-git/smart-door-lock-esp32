# 🔐 Smart Door Lock Using AI Face Recognition

A smart door access control system using **SCRFD** for face detection and **ArcFace (iResNet50 Fine-tuning)** for face recognition. The iResNet50 model was fine-tuned from the original InsightFace backbone for academic and research purposes, so its recognition performance may not be as accurate or robust as the official pretrained InsightFace models.

The project integrates **ESP32-CAM**, **FastAPI**, **MySQL**, and a web dashboard to provide real-time face registration, recognition, access monitoring, and automatic door unlocking.

> **Note**
>
> The Google Drive folder also provides the original **InsightFace backbone weights** and a mini version of the **CASIA-WebFace dataset** (approximately 1000 identities). These files are optional and are intended for users who want to reproduce the training process, perform transfer learning, or further fine-tune the ArcFace model.
>
> If you only want to run the face recognition system, downloading `last_backbone.pth` is sufficient.

---

# Features

## User Features

* Real-time camera preview from ESP32-CAM
* Automatic face verification every 2 seconds
* Face recognition using ArcFace
* Automatic door unlock when authentication succeeds
* Access denied for unknown users

---

## Administrator Features

* Register new users from ESP32-CAM
* Manage registered faces
* Search users by name
* Delete users
* Access log monitoring
* Web-based Admin Dashboard

---

# System Architecture

<img width="1537" height="1023" alt="Image" src="https://github.com/user-attachments/assets/7cb61836-fdee-4135-a3be-40de1a23f299" />

---

# Technologies

| Category         | Technology                      |
| ---------------- | ------------------------------- |
| Backend          | FastAPI                         |
| Deep Learning    | PyTorch                         |
| Face Detection   | SCRFD                           |
| Face Recognition | ArcFace (iResNet50 Fine-tuning) |
| Image Processing | OpenCV                          |
| Database         | MySQL                           |
| Embedded System  | ESP32-CAM                       |
| Frontend         | HTML, CSS, JavaScript           |
| Communication    | HTTP                            |

---

# 📂 Project Structure

```text
ai_server/

arcface_torch/

database/

esp32_cam/

web_dashboard/

requirements.txt

README.md

LICENSE
```
