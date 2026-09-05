// ESP32_Sensor.ino
// HC-SR04 + ESP32 + EcoHaul backend entegrasyonu (tek dosya)

// ====== KÜRESEL AYARLAR ======
#include <WiFi.h>
#include <HTTPClient.h>

// --- PINLER ---
const int TRIG_PIN = 15;
const int ECHO_PIN = 14;

// --- BİN GEOMETRİSİ ---
const float BIN_HEIGHT_CM   = 100.0f; // gerçek yüksekliği sonra ölçüp değiştir
const float SENSOR_OFFSET_CM = 3.0f;  // sensör ile referans seviye arası offset (3–4 cm civarı)

// --- ÖLÇÜM / SLEEP AYARLARI ---
const int NUM_SAMPLES = 10;                   // median için örnek sayısı
const uint64_t SLEEP_INTERVAL_SECONDS = 3600; // 1 saat
const int HEARTBEAT_WAKE_INTERVAL = 8;        // 8 uyanma = 8 saat

// --- WiFi & Backend ayarları ---
const char* WIFI_SSID     = "Atahan adlı kişiye ait S26";
const char* WIFI_PASSWORD = "sharku241";

// PC'n nin IP adresini ve backend portunu yaz
// Örnek: "http://192.168.1.133:8000"
const char* BACKEND_BASE_URL = "http://10.146.75.83:8000";

// Bu ESP32'nin temsil ettiği çöp kovası (bins_wgs84.csv içinden bir bin_id)
const char* BIN_ID = "WMS2564";

// ====== FILL LEVEL ENUM ======
enum class FillLevel {
  EMPTY,
  FULL,
  CRITICAL_FULL,
  SENSOR_ERROR
};

const char* fillLevelToString(FillLevel level) {
  switch (level) {
    case FillLevel::EMPTY:          return "EMPTY";
    case FillLevel::FULL:           return "FULL";
    case FillLevel::CRITICAL_FULL:  return "CRITICAL_FULL";
    case FillLevel::SENSOR_ERROR:
    default:                        return "SENSOR_ERROR";
  }
}

// RTC'de kalıcı olacak state (deep sleep sonrasında da korunur)
RTC_DATA_ATTR int rtc_lastLevelInt = -1;  // -1 = ilk boot
RTC_DATA_ATTR int rtc_wakeCounter  = 0;   // heartbeat için sayaç

// ====== MESAFE ÖLÇÜM FONKSİYONLARI ======
void initSensor() {
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(5);
}

float measureDistanceOnce(uint32_t timeoutMicros = 30000UL) {
  // Trigger pulse
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  // Echo okunuyor
  unsigned long duration = pulseIn(ECHO_PIN, HIGH, timeoutMicros);
  if (duration == 0) {
    return NAN; // timeout
  }

  // Ses hızı ~0.0343 cm/us, gidiş+geliş olduğu için /2
  float distanceCm = (duration / 2.0f) * 0.0343f;

  // HC-SR04 tipik aralık: 2–400 cm
  if (distanceCm < 2.0f || distanceCm > 400.0f) {
    return NAN;
  }

  return distanceCm;
}

int compareFloat(const void* a, const void* b) {
  float fa = *(const float*)a;
  float fb = *(const float*)b;
  if (fa < fb) return -1;
  if (fa > fb) return 1;
  return 0;
}

float measureMedianDistance(int numSamples = NUM_SAMPLES, uint32_t timeoutMicros = 30000UL) {
  if (numSamples <= 0) return NAN;

  float samples[NUM_SAMPLES];
  int validCount = 0;

  for (int i = 0; i < numSamples; ++i) {
    float d = measureDistanceOnce(timeoutMicros);
    if (!isnan(d)) {
      samples[validCount++] = d;
    }
    delay(50);
  }

  if (validCount == 0) {
    return NAN;
  }

  qsort(samples, validCount, sizeof(float), compareFloat);

  float median;
  if (validCount % 2 == 1) {
    median = samples[validCount / 2];
  } else {
    int mid = validCount / 2;
    median = (samples[mid - 1] + samples[mid]) / 2.0f;
  }

  return median;
}

// ====== DOLULUK YÜZDESİ & ENUM ======
float computeFillPercentage(float measuredDistanceCm) {
  if (isnan(measuredDistanceCm)) return NAN;

  float effectiveDistance = measuredDistanceCm - SENSOR_OFFSET_CM;
  if (effectiveDistance < 0.0f) effectiveDistance = 0.0f;

  float filledHeight = BIN_HEIGHT_CM - effectiveDistance;
  if (filledHeight < 0.0f)        filledHeight = 0.0f;
  if (filledHeight > BIN_HEIGHT_CM) filledHeight = BIN_HEIGHT_CM;

  float fillPct = (filledHeight / BIN_HEIGHT_CM) * 100.0f;
  if (fillPct < 0.0f)  fillPct = 0.0f;
  if (fillPct > 100.0f) fillPct = 100.0f;

  return fillPct;
}

FillLevel distanceToFillLevel(float measuredDistanceCm) {
  if (isnan(measuredDistanceCm)) {
    return FillLevel::SENSOR_ERROR;
  }

  float fillPct = computeFillPercentage(measuredDistanceCm);
  if (isnan(fillPct)) {
    return FillLevel::SENSOR_ERROR;
  }

  if (fillPct < 60.0f) {
    return FillLevel::EMPTY;
  } else if (fillPct < 90.0f) {
    return FillLevel::FULL;
  } else {
    return FillLevel::CRITICAL_FULL;
  }
}

// ====== WiFi & HTTP ======
bool connectWiFi(uint32_t timeoutMs = 15000) {
  Serial.println("[WiFi] Connecting...");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && (millis() - start) < timeoutMs) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("[WiFi] Connected, IP: ");
    Serial.println(WiFi.localIP());
    return true;
  } else {
    Serial.println("[WiFi] Failed to connect");
    WiFi.disconnect(true);
    return false;
  }
}

bool postJson(const String& url, const String& jsonBody) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[HTTP] WiFi not connected");
    return false;
  }

  HTTPClient http;
  http.begin(url);
  http.addHeader("Content-Type", "application/json");

  Serial.print("[HTTP] POST ");
  Serial.println(url);
  Serial.print("[HTTP] Body: ");
  Serial.println(jsonBody);

  int httpCode = http.POST(jsonBody);
  if (httpCode > 0) {
    Serial.print("[HTTP] Response code: ");
    Serial.println(httpCode);
    String payload = http.getString();
    Serial.print("[HTTP] Response body: ");
    Serial.println(payload);
  } else {
    Serial.print("[HTTP] POST failed, error: ");
    Serial.println(http.errorToString(httpCode));
  }

  http.end();
  return (httpCode >= 200 && httpCode < 300);
}

bool sendStateChange(float medianDistance, FillLevel level) {
  String url = String(BACKEND_BASE_URL) + "/api/devices/" + BIN_ID + "/state-change";

  String body = "{";
  body += "\"enum_state\":\"";
  body += fillLevelToString(level);
  body += "\"";

  if (!isnan(medianDistance)) {
    body += ",\"median_distance_cm\":";
    body += String(medianDistance, 2);
  }

  body += "}";

  return postJson(url, body);
}

bool sendHeartbeat(FillLevel level) {
  String url = String(BACKEND_BASE_URL) + "/api/devices/" + BIN_ID + "/heartbeat";

  String body = "{";
  body += "\"current_enum\":\"";
  body += fillLevelToString(level);
  body += "\"";
  body += "}";

  return postJson(url, body);
}

// ====== DEEP SLEEP ======
void goToDeepSleep() {
  uint64_t sleepMicros = SLEEP_INTERVAL_SECONDS * 1000000ULL;
  Serial.print("[SLEEP] Going to deep sleep for ");
  Serial.print(SLEEP_INTERVAL_SECONDS);
  Serial.println(" seconds...");

  esp_sleep_enable_timer_wakeup(sleepMicros);
  Serial.flush();
  esp_deep_sleep_start();
}

// ====== SETUP / LOOP ======
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println();
  Serial.println("=== EcoHaul ESP32 Sensor ===");

  initSensor();

  // 1) Ölçüm + enum
  float medianDistance = measureMedianDistance();
  FillLevel currentLevel = distanceToFillLevel(medianDistance);
  float fillPct = computeFillPercentage(medianDistance);

  Serial.print("Median distance (cm): ");
  if (isnan(medianDistance)) Serial.println("NAN");
  else                       Serial.println(medianDistance, 2);

  Serial.print("Fill level: ");
  Serial.println(fillLevelToString(currentLevel));

  Serial.print("Fill percentage: ");
  if (isnan(fillPct)) Serial.println("NAN");
  else {
    Serial.print(fillPct, 1);
    Serial.println(" %");
  }

  // 2) Enum değişimi ve heartbeat mantığı
  int currentLevelInt = (int)currentLevel;
  bool firstBoot      = (rtc_lastLevelInt == -1);
  bool levelChanged   = (!firstBoot && currentLevelInt != rtc_lastLevelInt);
  bool forceHeartbeat = (rtc_wakeCounter >= HEARTBEAT_WAKE_INTERVAL);

  Serial.print("rtc_lastLevelInt: ");
  Serial.println(rtc_lastLevelInt);
  Serial.print("rtc_wakeCounter: ");
  Serial.println(rtc_wakeCounter);
  Serial.print("levelChanged: ");
  Serial.println(levelChanged ? "YES" : "NO");
  Serial.print("forceHeartbeat: ");
  Serial.println(forceHeartbeat ? "YES" : "NO");

  bool needWifi = firstBoot || levelChanged || forceHeartbeat;

  if (needWifi) {
    if (connectWiFi()) {
      bool ok = true;

      // İlk boot veya enum değiştiyse → state-change (aynı zamanda heartbeat gibi)
      if (firstBoot || levelChanged) {
        ok = sendStateChange(medianDistance, currentLevel);
      } 
      // Sadece heartbeat gerekiyorsa
      else if (forceHeartbeat) {
        ok = sendHeartbeat(currentLevel);
      }

      if (ok) {
        // Başarılı istekte sayaç sıfırlanır
        rtc_wakeCounter = 0;
      } else {
        // Başarısız ise, sayaç artmaya devam eder (bir dahaki sefer tekrar dener)
        rtc_wakeCounter++;
      }

      WiFi.disconnect(true);
      WiFi.mode(WIFI_OFF);
    } else {
      // WiFi bağlanamazsa; sadece sayaç artar
      rtc_wakeCounter++;
    }
  } else {
    // Ne değişim ne heartbeat zamanı → sadece sayaç artar
    rtc_wakeCounter++;
  }

  // Son enum'u RTC'ye yaz
  rtc_lastLevelInt = currentLevelInt;

  Serial.print("New rtc_lastLevelInt: ");
  Serial.println(rtc_lastLevelInt);
  Serial.print("New rtc_wakeCounter: ");
  Serial.println(rtc_wakeCounter);

  // 3) Deepsleep
  goToDeepSleep();
}

void loop() {
  // Kullanılmıyor; deep sleep sonrası reset ile tekrar setup() çalışır.
}