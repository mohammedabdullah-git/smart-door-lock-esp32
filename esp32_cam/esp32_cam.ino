#include "esp_camera.h"
#include <WiFi.h>
#include "esp_http_server.h"

// ============================================================
// WIFI CONFIG
// ============================================================

const char* WIFI_SSID = "manghainguoi";
const char* WIFI_PASSWORD = "xinloinhe";


// ============================================================
// RELAY + DOOR LOCK CONFIG
// ============================================================

// Chân điều khiển relay.
// Nếu bạn nối relay vào chân khác thì sửa tại đây.
#define RELAY_PIN 13

// Thời gian mở khóa: 5 giây
#define UNLOCK_DURATION_MS 5000

// Nếu relay của bạn kích mức HIGH:
// RELAY_ACTIVE_LEVEL = HIGH
// RELAY_INACTIVE_LEVEL = LOW
//
// Nếu relay của bạn kích mức LOW:
// RELAY_ACTIVE_LEVEL = LOW
// RELAY_INACTIVE_LEVEL = HIGH

#define RELAY_ACTIVE_LEVEL HIGH
#define RELAY_INACTIVE_LEVEL LOW

bool doorUnlocked = false;
unsigned long unlockStartTime = 0;


// ============================================================
// AI THINKER ESP32-CAM PIN CONFIG
// ============================================================

#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27

#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5

#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22


// ============================================================
// HTTP SERVER
// ============================================================

httpd_handle_t camera_httpd = NULL;
httpd_handle_t stream_httpd = NULL;

static const char* STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=frame";
static const char* STREAM_BOUNDARY = "\r\n--frame\r\n";
static const char* STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";


// ============================================================
// CORS HELPER
// ============================================================

void set_cors_headers(httpd_req_t *req) {
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  httpd_resp_set_hdr(req, "Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  httpd_resp_set_hdr(req, "Access-Control-Allow-Headers", "*");
}


// ============================================================
// RELAY CONTROL
// ============================================================

void lockDoor() {
  digitalWrite(RELAY_PIN, RELAY_INACTIVE_LEVEL);
  doorUnlocked = false;

  Serial.println("[DOOR] Relay OFF - Door locked");
}


void unlockDoor() {
  digitalWrite(RELAY_PIN, RELAY_ACTIVE_LEVEL);
  doorUnlocked = true;
  unlockStartTime = millis();

  Serial.println("[DOOR] Relay ON - Door unlocked");
}


// ============================================================
// ROOT: /
// ============================================================

static esp_err_t root_handler(httpd_req_t *req) {
  String html = "";
  html += "<!DOCTYPE html><html><head><title>ESP32-CAM Smart Door</title></head><body>";
  html += "<h1>ESP32-CAM Smart Door</h1>";
  html += "<p><a href='/capture'>Capture Image</a></p>";
  html += "<p><a href='http://";
  html += WiFi.localIP().toString();
  html += ":81/stream'>MJPEG Stream</a></p>";
  html += "<p><a href='/status'>Status JSON</a></p>";
  html += "<p><a href='/command?msg=HelloESP32'>Send Test Command</a></p>";
  html += "<p><a href='/unlock'>Unlock Door</a></p>";
  html += "<p><a href='/lock'>Lock Door</a></p>";
  html += "</body></html>";

  set_cors_headers(req);
  httpd_resp_set_type(req, "text/html");

  return httpd_resp_send(req, html.c_str(), html.length());
}


// ============================================================
// CAPTURE: /capture
// ============================================================

static esp_err_t capture_handler(httpd_req_t *req) {
  camera_fb_t *fb = esp_camera_fb_get();

  if (!fb) {
    Serial.println("[ERROR] Camera capture failed");
    httpd_resp_send_500(req);
    return ESP_FAIL;
  }

  Serial.println("[ESP32 -> WEB/AI] /capture requested, sending JPEG image");

  set_cors_headers(req);
  httpd_resp_set_type(req, "image/jpeg");
  httpd_resp_set_hdr(req, "Content-Disposition", "inline; filename=capture.jpg");

  esp_err_t res = httpd_resp_send(req, (const char *)fb->buf, fb->len);

  esp_camera_fb_return(fb);

  return res;
}


// ============================================================
// STREAM: :81/stream
// ============================================================

static esp_err_t stream_handler(httpd_req_t *req) {
  camera_fb_t *fb = NULL;
  esp_err_t res = ESP_OK;
  char part_buf[64];

  set_cors_headers(req);

  res = httpd_resp_set_type(req, STREAM_CONTENT_TYPE);

  if (res != ESP_OK) {
    return res;
  }

  Serial.println("[ESP32 -> WEB] MJPEG stream started");

  while (true) {
    fb = esp_camera_fb_get();

    if (!fb) {
      Serial.println("[ERROR] Camera capture failed in stream");
      res = ESP_FAIL;
      break;
    }

    if (fb->format != PIXFORMAT_JPEG) {
      Serial.println("[ERROR] Non-JPEG frame not supported");
      esp_camera_fb_return(fb);
      res = ESP_FAIL;
      break;
    }

    res = httpd_resp_send_chunk(req, STREAM_BOUNDARY, strlen(STREAM_BOUNDARY));

    if (res == ESP_OK) {
      size_t hlen = snprintf(part_buf, sizeof(part_buf), STREAM_PART, fb->len);
      res = httpd_resp_send_chunk(req, part_buf, hlen);
    }

    if (res == ESP_OK) {
      res = httpd_resp_send_chunk(req, (const char *)fb->buf, fb->len);
    }

    esp_camera_fb_return(fb);
    fb = NULL;

    if (res != ESP_OK) {
      break;
    }

    delay(50);
  }

  Serial.println("[ESP32 -> WEB] MJPEG stream ended");

  return res;
}


// ============================================================
// STATUS: /status
// ============================================================

static esp_err_t status_handler(httpd_req_t *req) {
  String response = "{";
  response += "\"success\":true,";
  response += "\"device\":\"ESP32-CAM\",";
  response += "\"ip\":\"";
  response += WiFi.localIP().toString();
  response += "\",";
  response += "\"relay_pin\":";
  response += String(RELAY_PIN);
  response += ",";
  response += "\"door_unlocked\":";
  response += doorUnlocked ? "true" : "false";
  response += ",";
  response += "\"unlock_duration_ms\":";
  response += String(UNLOCK_DURATION_MS);
  response += ",";
  response += "\"capture_url\":\"http://";
  response += WiFi.localIP().toString();
  response += "/capture\",";
  response += "\"stream_url\":\"http://";
  response += WiFi.localIP().toString();
  response += ":81/stream\",";
  response += "\"unlock_url\":\"http://";
  response += WiFi.localIP().toString();
  response += "/unlock\",";
  response += "\"lock_url\":\"http://";
  response += WiFi.localIP().toString();
  response += "/lock\",";
  response += "\"command_url\":\"http://";
  response += WiFi.localIP().toString();
  response += "/command?msg=hello\"";
  response += "}";

  Serial.println("[ESP32 -> WEB/AI] /status requested, sending JSON");

  set_cors_headers(req);
  httpd_resp_set_type(req, "application/json");

  return httpd_resp_send(req, response.c_str(), response.length());
}


// ============================================================
// COMMAND: /command?msg=...
// Dùng để test gửi dữ liệu xuống ESP32.
// Không điều khiển relay.
// ============================================================

static esp_err_t command_handler(httpd_req_t *req) {
  char query[128];
  char msg[100];

  String receivedMsg = "";

  if (httpd_req_get_url_query_str(req, query, sizeof(query)) == ESP_OK) {
    if (httpd_query_key_value(query, "msg", msg, sizeof(msg)) == ESP_OK) {
      receivedMsg = String(msg);
    }
  }

  if (receivedMsg == "") {
    receivedMsg = "NO_MESSAGE";
  }

  Serial.print("[WEB/AI -> ESP32] Received command: ");
  Serial.println(receivedMsg);

  String response = "{";
  response += "\"success\":true,";
  response += "\"message\":\"ESP32-CAM received command\",";
  response += "\"received\":\"";
  response += receivedMsg;
  response += "\"";
  response += "}";

  set_cors_headers(req);
  httpd_resp_set_type(req, "application/json");

  return httpd_resp_send(req, response.c_str(), response.length());
}


// ============================================================
// UNLOCK: /unlock
// Chỉ FastAPI gọi endpoint này khi AI nhận diện ACCEPT.
// ============================================================

static esp_err_t unlock_handler(httpd_req_t *req) {
  Serial.println("[AI SERVER -> ESP32] /unlock called");

  if (!doorUnlocked) {
    unlockDoor();
    Serial.println("[DOOR] Door will auto lock after timeout");
  } else {
    Serial.println("[DOOR] Door already unlocked. Ignore repeated unlock command");
  }

  String response = "{";
  response += "\"success\":true,";
  response += "\"message\":\"Unlock command accepted\",";
  response += "\"door_unlocked\":";
  response += doorUnlocked ? "true" : "false";
  response += ",";
  response += "\"auto_lock_after_ms\":";
  response += String(UNLOCK_DURATION_MS);
  response += "}";

  set_cors_headers(req);
  httpd_resp_set_type(req, "application/json");

  return httpd_resp_send(req, response.c_str(), response.length());
}


// ============================================================
// LOCK: /lock
// Endpoint test khóa lại thủ công.
// Bình thường không cần FastAPI gọi /lock.
// ============================================================

static esp_err_t lock_handler(httpd_req_t *req) {
  Serial.println("[WEB/AI -> ESP32] /lock called");

  lockDoor();

  String response = "{";
  response += "\"success\":true,";
  response += "\"message\":\"Door locked\",";
  response += "\"door_unlocked\":false";
  response += "}";

  set_cors_headers(req);
  httpd_resp_set_type(req, "application/json");

  return httpd_resp_send(req, response.c_str(), response.length());
}


// ============================================================
// START SERVER
// ============================================================

void startCameraServer() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 80;

  httpd_uri_t root_uri = {
    .uri       = "/",
    .method    = HTTP_GET,
    .handler   = root_handler,
    .user_ctx  = NULL
  };

  httpd_uri_t capture_uri = {
    .uri       = "/capture",
    .method    = HTTP_GET,
    .handler   = capture_handler,
    .user_ctx  = NULL
  };

  httpd_uri_t status_uri = {
    .uri       = "/status",
    .method    = HTTP_GET,
    .handler   = status_handler,
    .user_ctx  = NULL
  };

  httpd_uri_t command_uri = {
    .uri       = "/command",
    .method    = HTTP_GET,
    .handler   = command_handler,
    .user_ctx  = NULL
  };

  httpd_uri_t unlock_uri = {
    .uri       = "/unlock",
    .method    = HTTP_GET,
    .handler   = unlock_handler,
    .user_ctx  = NULL
  };

  httpd_uri_t lock_uri = {
    .uri       = "/lock",
    .method    = HTTP_GET,
    .handler   = lock_handler,
    .user_ctx  = NULL
  };

  if (httpd_start(&camera_httpd, &config) == ESP_OK) {
    httpd_register_uri_handler(camera_httpd, &root_uri);
    httpd_register_uri_handler(camera_httpd, &capture_uri);
    httpd_register_uri_handler(camera_httpd, &status_uri);
    httpd_register_uri_handler(camera_httpd, &command_uri);
    httpd_register_uri_handler(camera_httpd, &unlock_uri);
    httpd_register_uri_handler(camera_httpd, &lock_uri);
  }

  httpd_config_t stream_config = HTTPD_DEFAULT_CONFIG();
  stream_config.server_port = 81;
  stream_config.ctrl_port = 32769;

  httpd_uri_t stream_uri = {
    .uri       = "/stream",
    .method    = HTTP_GET,
    .handler   = stream_handler,
    .user_ctx  = NULL
  };

  if (httpd_start(&stream_httpd, &stream_config) == ESP_OK) {
    httpd_register_uri_handler(stream_httpd, &stream_uri);
  }
}


// ============================================================
// CAMERA SETUP
// ============================================================

bool setupCamera() {
  camera_config_t config;

  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;

  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;

  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;

  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;

  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;

  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  if (psramFound()) {
    config.frame_size = FRAMESIZE_VGA;
    config.jpeg_quality = 10;
    config.fb_count = 2;
  } else {
    config.frame_size = FRAMESIZE_QVGA;
    config.jpeg_quality = 12;
    config.fb_count = 1;
  }

  esp_err_t err = esp_camera_init(&config);

  if (err != ESP_OK) {
    Serial.printf("[ERROR] Camera init failed with error 0x%x\n", err);
    return false;
  }

  sensor_t *s = esp_camera_sensor_get();

  s->set_brightness(s, 0);
  s->set_contrast(s, 0);
  s->set_saturation(s, 0);

  s->set_vflip(s, 1);

  return true;
}


// ============================================================
// SETUP
// ============================================================

void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(false);
  Serial.println();

  // Setup relay trước, mặc định khóa ở trạng thái OFF
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, RELAY_INACTIVE_LEVEL);
  doorUnlocked = false;

  Serial.println("[SYSTEM] Relay initialized");
  Serial.print("[SYSTEM] Relay pin: GPIO ");
  Serial.println(RELAY_PIN);

  if (!setupCamera()) {
    Serial.println("[ERROR] Camera setup failed. Restarting...");
    delay(3000);
    ESP.restart();
  }

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("Connecting to WiFi");

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();
  Serial.println("WiFi connected");

  IPAddress ip = WiFi.localIP();

  Serial.println("====================================");
  Serial.print("ESP32-CAM IP address: ");
  Serial.println(ip);

  Serial.print("Home URL: http://");
  Serial.println(ip);

  Serial.print("Capture URL: http://");
  Serial.print(ip);
  Serial.println("/capture");

  Serial.print("Stream URL: http://");
  Serial.print(ip);
  Serial.println(":81/stream");

  Serial.print("Status URL: http://");
  Serial.print(ip);
  Serial.println("/status");

  Serial.print("Command URL: http://");
  Serial.print(ip);
  Serial.println("/command?msg=hello");

  Serial.print("Unlock URL: http://");
  Serial.print(ip);
  Serial.println("/unlock");

  Serial.print("Lock URL: http://");
  Serial.print(ip);
  Serial.println("/lock");

  Serial.println("====================================");

  startCameraServer();
}


// ============================================================
// LOOP
// ============================================================

void loop() {
  if (doorUnlocked && millis() - unlockStartTime >= UNLOCK_DURATION_MS) {
    Serial.println("[DOOR] Auto lock timeout reached");
    lockDoor();
  }

  delay(50);
}
