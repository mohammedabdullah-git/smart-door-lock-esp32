# ESP32-CAM Firmware

Firmware for the **Smart Door AI** project using ESP32-CAM AI Thinker.

## Hardware Requirements

* ESP32-CAM (AI Thinker)
* FTDI USB-to-Serial Adapter
* Relay SRD-05VDC-SL-C
* Solenoid Lock 12V
* External 12V Power Supply

---

## Required Libraries

The following libraries are included in the ESP32 Arduino Core:

* WiFi
* WebServer
* esp_camera

---

## Configuration

Edit WiFi credentials before uploading the firmware.

```cpp
const char* ssid = "YOUR_WIFI_NAME";
const char* password = "YOUR_WIFI_PASSWORD";
```

You can also modify the relay pin if necessary.

```cpp
#define RELAY_PIN 12
```

---

## 🔨 Upload Using Arduino IDE

### 1. Install ESP32 Board Package

Open **Arduino IDE**

```
File
 └── Preferences
```

Additional Boards Manager URLs:

```
https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
```

Then:

```
Tools
 └── Board
     └── Boards Manager
```

Install:

```
ESP32 by Espressif Systems
```

---

### 2. Board Configuration

Select:

```
Board           : AI Thinker ESP32-CAM
Upload Speed    : 115200
Partition Scheme: Huge APP
PSRAM           : Enabled
Flash Frequency : 80 MHz
```

---

### 3. Hardware Wiring Diagram

#### ESP32-CAM ↔ FTDI Programmer (for uploading firmware)

| FTDI Programmer | ESP32-CAM                    |
| --------------- | ---------------------------- |
| 5V              | 5V                           |
| GND             | GND                          |
| TX              | U0R                          |
| RX              | U0T                          |
| GND             | IO0 *(only while uploading)* |

#### ESP32-CAM ↔ Relay Module

| ESP32-CAM | Relay Module |
| --------- | ------------ |
| GPIO12    | IN           |
| 5V        | VCC          |
| GND       | GND          |

#### Relay Module ↔ Solenoid Lock

| Relay Module | Solenoid Lock / Power Supply |
| ------------ | ---------------------------- |
| COM          | +12V Power Supply            |
| NO           | Positive terminal of Lock    |
| GND          | Negative terminal of Lock    |

---

### 4. Notes

* Connect **IO0 to GND** only when uploading firmware.
* After uploading successfully, disconnect **IO0 from GND** and press the **RST** button to run the program normally.
* It is recommended to use an external **12V power supply** for the solenoid lock to ensure stable operation.

---

## 🌐 Available Endpoints

After connecting to WiFi, ESP32-CAM will print:

```text
Home URL
Capture URL
Stream URL
Status URL
Command URL
```

Example:

```text
http://192.168.1.100/capture
http://192.168.1.100:81/stream
```

---

## Features

* MJPEG video streaming
* JPEG image capture
* Receive commands from AI Server
* Relay control for door unlocking
* Communication with FastAPI AI Server

