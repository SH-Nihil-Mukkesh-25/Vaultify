#include <Arduino.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <MPU6050_light.h>
#include <SPI.h>
#include <MFRC522.h>
#include <ESP32Servo.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <base64.h>

#include "secrets.h"  // <-- Include secrets here

// -------------------- PIN ASSIGNMENTS --------------------
#define BUZZER_PIN 25
#define SERVO_PIN 26
#define I2C_SDA_PIN 21
#define I2C_SCL_PIN 22
#define RFID_SS_PIN 5
#define RFID_RST_PIN 4

// -------------------- CONFIG --------------------
#define SERVO_LOCKED_POS 70
#define SERVO_UNLOCKED_POS 160
#define ACCEL_THRESHOLD 0.6
#define DOOR_AUTO_CLOSE 120000
#define ALARM_DURATION 120000

// -------------------- OBJECTS --------------------
LiquidCrystal_I2C lcd(0x27,16,2);
MPU6050 mpu(Wire);
MFRC522 rfid(RFID_SS_PIN, RFID_RST_PIN);
Servo doorServo;

// -------------------- STATES --------------------
bool alarmActive = false;
bool theftLockActive = false;
unsigned long alarmStartTime = 0;
bool doorOpen = false;
unsigned long doorOpenTime = 0;

// -------------------- VALID CARDS --------------------
byte validCards[][4] = {
  {0x3D, 0xF3, 0x3B, 0x06},
  {0x6C, 0x82, 0x8C, 0x00}
};
const int NUM_VALID_CARDS = sizeof(validCards) / sizeof(validCards[0]);

// -------------------- BUZZER --------------------
unsigned long lastBeepTime = 0;
bool buzzerState = false;

// -------------------- HELPERS --------------------
void shortBeep(int times){
  for(int i=0;i<times;i++){
    tone(BUZZER_PIN,2500);
    delay(150);
    noTone(BUZZER_PIN);
    delay(150);
  }
}

String urlencode(const String &str) {
  String encoded = "";
  char c;
  char buf[4];
  for (size_t i = 0; i < str.length(); i++) {
    c = str.charAt(i);
    if ((c >= '0' && c <= '9') || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
        c == '-' || c == '_' || c == '.' || c == '~') encoded += c;
    else if (c == ' ') encoded += '+';
    else { sprintf(buf, "%%%02X", (unsigned char)c); encoded += buf; }
  }
  return encoded;
}

// -------------------- SMS --------------------
void sendSms(String msg){
  if(WiFi.status() != WL_CONNECTED) return;
  HTTPClient http;
  String url = "https://api.twilio.com/2010-04-01/Accounts/" + TWILIO_ACCOUNT_SID + "/Messages.json";
  http.begin(url);
  String basicAuth = base64::encode(TWILIO_ACCOUNT_SID + ":" + TWILIO_AUTH_TOKEN);
  http.addHeader("Authorization", "Basic " + basicAuth);
  http.addHeader("Content-Type", "application/x-www-form-urlencoded");
  String body = "To=" + DEST_PHONE + "&From=" + TWILIO_FROM_NUMBER + "&Body=" + urlencode(msg);
  http.POST(body);
  http.end();
}

// -------------------- BACKEND LOGGING --------------------
void sendToBackend(String eventType, String detail){
  if(WiFi.status() != WL_CONNECTED){
    Serial.println("WiFi not connected, skipping backend log");
    return;
  }
  HTTPClient http;
  http.begin(BACKEND_URL + "/api/logs");
  http.addHeader("Content-Type","application/json");
  String payload = "{\"event\":\""+eventType+"\",\"detail\":\""+detail+"\"}";
  http.setTimeout(5000); // 5 second timeout
  int httpCode = http.POST(payload);
  
  if(httpCode > 0){
    Serial.printf("Backend responded: %d\n", httpCode);
    if(httpCode == 200){
      Serial.println("Log sent successfully");
    }
  } else {
    Serial.printf("Backend request failed: %s\n", http.errorToString(httpCode).c_str());
  }
  http.end();
}
// -------------------- LCD --------------------
void updateLcdDisplay(){
  lcd.clear();
  if(alarmActive){
    lcd.setCursor(0,0); lcd.print("!!! THEFT ALERT !!!");
    lcd.setCursor(0,1); lcd.print("Door Locked!");
  } else if(doorOpen){
    lcd.setCursor(0,0); lcd.print("Door is Unlocked");
    unsigned long timeLeft = (DOOR_AUTO_CLOSE-(millis()-doorOpenTime))/1000;
    lcd.setCursor(0,1); lcd.print("Auto-Lock in "); lcd.print(timeLeft); lcd.print("s");
  } else {
    lcd.setCursor(0,0); lcd.print("System Normal");
    lcd.setCursor(0,1); lcd.print("Door is Locked");
  }
}

// -------------------- LOGIC --------------------
void handleMotionSensor(){
  mpu.update();
  float acc = sq(mpu.getAccX()) + sq(mpu.getAccY());
  if(acc > sq(ACCEL_THRESHOLD) && !alarmActive){
    alarmActive = true;
    theftLockActive = true;
    alarmStartTime = millis();
    doorServo.write(SERVO_LOCKED_POS);
    doorOpen = false;
    updateLcdDisplay();
    sendSms("ALERT: Theft detected!");
    sendToBackend("motion_alert","Possible intrusion detected");
  }
}

void handleRfidReader(){
  if(rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()){
    bool valid = false;
    for(int i=0;i<NUM_VALID_CARDS;i++){
      if(rfid.uid.size==sizeof(validCards[i]) &&
         memcmp(rfid.uid.uidByte, validCards[i], sizeof(validCards[i]))==0) { valid=true; break; }
    }

    if(valid){
      shortBeep(1);
      if(alarmActive && theftLockActive){
        alarmActive = false; theftLockActive = false;
        lcd.clear(); lcd.setCursor(0,0); lcd.print("Theft Alarm Off"); delay(1500);
        sendSms("Theft alarm deactivated.");
        sendToBackend("rfid_valid","Theft alarm deactivated");
      } else if(!theftLockActive){
        doorOpen = !doorOpen;
        if(doorOpen){ 
          doorServo.write(SERVO_UNLOCKED_POS); 
          doorOpenTime=millis(); 
          sendSms("Door unlocked."); 
          sendToBackend("door_unlocked","RFID authorized"); 
        } else { 
          doorServo.write(SERVO_LOCKED_POS); 
          sendSms("Door locked."); 
          sendToBackend("door_locked","RFID authorized"); 
        }
      }
    } else {
      shortBeep(3);
      lcd.clear(); lcd.setCursor(0,0); lcd.print("Access Denied!");
      sendSms("ALERT: Invalid RFID attempt!");
      sendToBackend("rfid_invalid","Unauthorized card scanned");
      delay(2000);
    }
    updateLcdDisplay();
    rfid.PICC_HaltA(); rfid.PCD_StopCrypto1();
  }
}

void handleAlarmState(){
  if(alarmActive){
    unsigned long current = millis();
    if(buzzerState && (current - lastBeepTime >= 1000)){ noTone(BUZZER_PIN); buzzerState=false; lastBeepTime=current; }
    else if(!buzzerState && (current - lastBeepTime >= 100)){ tone(BUZZER_PIN,3000); buzzerState=true; lastBeepTime=current; }
  } else { noTone(BUZZER_PIN); buzzerState=false; }
}

void handleDoorState(){
  if(doorOpen && (millis()-doorOpenTime > DOOR_AUTO_CLOSE)){
    doorServo.write(SERVO_LOCKED_POS); doorOpen=false;
    sendSms("Door auto-locked."); 
    sendToBackend("door_autolock","Auto-lock executed");
    updateLcdDisplay();
  }
}

// -------------------- SETUP --------------------
void setup(){
  Serial.begin(115200);
  Wire.begin(I2C_SDA_PIN,I2C_SCL_PIN);
  lcd.init(); lcd.backlight(); lcd.setCursor(0,0); lcd.print("System Booting...");
  delay(1500);

  WiFi.begin(WIFI_SSID,WIFI_PASS); lcd.setCursor(0,1); lcd.print("Connecting Wi-Fi...");
  while(WiFi.status()!=WL_CONNECTED){ delay(500); Serial.print("."); }
  lcd.setCursor(0,1); lcd.print("Wi-Fi Connected   ");

  doorServo.attach(SERVO_PIN); doorServo.write(SERVO_LOCKED_POS);
  if(mpu.begin()!=0){ lcd.clear(); lcd.setCursor(0,0); lcd.print("MPU-6050 ERROR!"); while(1); }
  mpu.calcOffsets();

  SPI.begin(); rfid.PCD_Init();
  updateLcdDisplay();
  Serial.println("System Ready.");
}

// -------------------- LOOP --------------------
unsigned long lastLcdUpdate = 0;
const long LCD_UPDATE_INTERVAL = 1000; // Update every 1 second

void loop(){
  handleMotionSensor();
  handleRfidReader();
  handleAlarmState();
  handleDoorState();
  
  // Only update LCD every second
  if(millis() - lastLcdUpdate > LCD_UPDATE_INTERVAL){
    updateLcdDisplay();
    lastLcdUpdate = millis();
  }
}

// old v1 code 👇

// #include <Arduino.h>
// #include <Wire.h>
// #include <LiquidCrystal_I2C.h>
// #include <MPU6050_light.h>
// #include <SPI.h>
// #include <MFRC522.h>
// #include <ESP32Servo.h>
// #include <WiFi.h>
// #include <HTTPClient.h>
// #include <base64.h>  // For Basic Auth

// // -------------------- PIN ASSIGNMENTS --------------------
// #define BUZZER_PIN 25
// #define SERVO_PIN 26
// #define I2C_SDA_PIN 21
// #define I2C_SCL_PIN 22
// #define RFID_SS_PIN 5
// #define RFID_RST_PIN 4

// // -------------------- CONFIG --------------------
// #define SERVO_LOCKED_POS 70
// #define SERVO_UNLOCKED_POS 160
// #define ACCEL_THRESHOLD 0.6

// // -------------------- WIFI --------------------
// const char* ssid = "YOUR_WIFI_SSID";       // <-- Fill your Wi-Fi SSID
// const char* password = "YOUR_WIFI_PASS";   // <-- Fill your Wi-Fi Password

// // -------------------- TWILIO --------------------
// const String TWILIO_ACCOUNT_SID = "YOUR_TWILIO_SID";      // <-- Fill Twilio Account SID
// const String TWILIO_AUTH_TOKEN  = "YOUR_TWILIO_TOKEN";   // <-- Fill Twilio Auth Token
// const String DEST_PHONE = "+91XXXXXXXXXX";                // <-- Fill destination phone number
// const String TWILIO_FROM_NUMBER = "+1XXXXXXXXXX";        // <-- Fill Twilio phone number

// // -------------------- OBJECTS --------------------
// LiquidCrystal_I2C lcd(0x27,16,2);
// MPU6050 mpu(Wire);
// MFRC522 rfid(RFID_SS_PIN, RFID_RST_PIN);
// Servo doorServo;

// // -------------------- STATES & TIMERS --------------------
// bool alarmActive = false;
// bool theftLockActive = false;   // door locked due to theft
// unsigned long alarmStartTime = 0;
// const unsigned long ALARM_DURATION = 120000;

// bool doorOpen = false;
// unsigned long doorOpenTime = 0;
// const unsigned long DOOR_AUTO_CLOSE = 120000;

// // -------------------- VALID CARDS --------------------
// byte validCards[][4] = {
//   {0x3D, 0xF3, 0x3B, 0x06},  // <-- Example card 1
//   {0x6C, 0x82, 0x8C, 0x00}   // <-- Example card 2
// };
// const int NUM_VALID_CARDS = sizeof(validCards) / sizeof(validCards[0]);

// // -------------------- BUZZER TIMING --------------------
// unsigned long lastBeepTime = 0;
// bool buzzerState = false; // ON/OFF

// // -------------------- HELPERS --------------------
// void shortBeep(int times){
//   for(int i=0;i<times;i++){
//     tone(BUZZER_PIN,2500);
//     delay(150);
//     noTone(BUZZER_PIN);
//     delay(150);
//   }
// }

// String urlencode(const String &str) {
//   String encoded = "";
//   char c;
//   char buf[4];
//   for (size_t i = 0; i < str.length(); i++) {
//     c = str.charAt(i);
//     if ((c >= '0' && c <= '9') ||
//         (c >= 'a' && c <= 'z') ||
//         (c >= 'A' && c <= 'Z') ||
//         c == '-' || c == '_' || c == '.' || c == '~') {
//       encoded += c;
//     } else if (c == ' ') {
//       encoded += '+';
//     } else {
//       sprintf(buf, "%%%02X", (unsigned char)c);
//       encoded += buf;
//     }
//   }
//   return encoded;
// }

// // -------------------- SMS FUNCTION WITH RETRY --------------------
// const int MAX_RETRIES = 3;
// const int RETRY_DELAY = 5000; // ms

// void sendSms(String msg){
//   if(WiFi.status() != WL_CONNECTED){
//     Serial.println("WiFi not connected - cannot send SMS");
//     return;
//   }

//   int attempt = 0;
//   bool sent = false;

//   while(attempt < MAX_RETRIES && !sent){
//     attempt++;
//     HTTPClient http;
//     String url = "https://api.twilio.com/2010-04-01/Accounts/" + TWILIO_ACCOUNT_SID + "/Messages.json";
//     http.begin(url);

//     String basicAuth = base64::encode(TWILIO_ACCOUNT_SID + ":" + TWILIO_AUTH_TOKEN);
//     http.addHeader("Authorization", "Basic " + basicAuth);
//     http.addHeader("Content-Type", "application/x-www-form-urlencoded");

//     String body = "To=" + DEST_PHONE + "&From=" + TWILIO_FROM_NUMBER + "&Body=" + urlencode(msg);

//     int httpCode = http.POST(body);
//     if(httpCode > 0){
//       Serial.print("HTTP code: "); Serial.println(httpCode);
//       String response = http.getString();
//       Serial.println("Response: " + response);
//       sent = true;
//     } else {
//       Serial.print("HTTP POST failed, attempt "); Serial.print(attempt); Serial.print(", error: "); Serial.println(httpCode);
//       delay(RETRY_DELAY);
//     }
//     http.end();
//   }

//   if(!sent){
//     Serial.println("Failed to send SMS after multiple attempts!");
//   }
// }

// // -------------------- LCD --------------------
// void updateLcdDisplay(){
//   lcd.clear();
//   if(alarmActive){
//     lcd.setCursor(0,0);
//     lcd.print("!!! THEFT ALERT !!!");
//     lcd.setCursor(0,1);
//     lcd.print("Door Locked!");
//   } else if(doorOpen){
//     lcd.setCursor(0,0);
//     lcd.print("Door is Unlocked");
//     unsigned long timeLeft = (DOOR_AUTO_CLOSE-(millis()-doorOpenTime))/1000;
//     lcd.setCursor(0,1);
//     lcd.print("Auto-Lock in ");
//     lcd.print(timeLeft);
//     lcd.print("s");
//   } else {
//     lcd.setCursor(0,0);
//     lcd.print("System Normal");
//     lcd.setCursor(0,1);
//     lcd.print("Door is Locked");
//   }
// }

// // -------------------- LOGIC HANDLERS --------------------
// void handleMotionSensor(){
//   mpu.update();
//   float acc = sq(mpu.getAccX()) + sq(mpu.getAccY());
//   if(acc > sq(ACCEL_THRESHOLD) && !alarmActive){
//     alarmActive = true;
//     theftLockActive = true;  // Door locked due to theft
//     alarmStartTime = millis();
//     Serial.println("Theft detected!");
//     updateLcdDisplay();
//     sendSms("ALERT: Theft detected!");
//     doorServo.write(SERVO_LOCKED_POS);
//     doorOpen = false;
//   }
// }

// void handleRfidReader(){
//   if(rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()){
//     bool valid = false;

//     // compare against all valid cards
//     for(int i=0; i<NUM_VALID_CARDS; i++){
//       if(rfid.uid.size == sizeof(validCards[i]) &&
//          memcmp(rfid.uid.uidByte, validCards[i], sizeof(validCards[i])) == 0){
//         valid = true;
//         break;
//       }
//     }

//     if(valid){
//       Serial.println("Valid card.");
//       shortBeep(1);

//       if(alarmActive && theftLockActive){
//         // Only deactivate theft alarm, DO NOT open door immediately
//         alarmActive = false;
//         theftLockActive = false;
//         lcd.clear();
//         lcd.setCursor(0,0);
//         lcd.print("Theft Alarm Off");
//         delay(1500);
//         sendSms("Theft alarm deactivated.");
//       } else if(!theftLockActive){
//         // Normal door toggle
//         doorOpen = !doorOpen;
//         if(doorOpen){
//           doorServo.write(SERVO_UNLOCKED_POS);
//           doorOpenTime = millis();
//           Serial.println("Door Unlocked.");
//           sendSms("Door unlocked.");
//         } else {
//           doorServo.write(SERVO_LOCKED_POS);
//           Serial.println("Door Locked.");
//           sendSms("Door locked.");
//         }
//       }
//     } else {
//       Serial.println("Invalid card.");
//       shortBeep(3);
//       lcd.clear();
//       lcd.setCursor(0,0);
//       lcd.print("Access Denied!");
//       sendSms("ALERT: Invalid RFID attempt!");
//       delay(2000);
//     }

//     updateLcdDisplay();
//     rfid.PICC_HaltA();
//     rfid.PCD_StopCrypto1();
//   }
// }

// void handleAlarmState(){
//   if(alarmActive){
//     unsigned long current = millis();
//     if(buzzerState && (current - lastBeepTime >= 1000)){ // ON for 1000ms
//       noTone(BUZZER_PIN);
//       buzzerState = false;
//       lastBeepTime = current;
//     } else if(!buzzerState && (current - lastBeepTime >= 100)){ // OFF for 100ms
//       tone(BUZZER_PIN, 3000); // 3kHz
//       buzzerState = true;
//       lastBeepTime = current;
//     }
//   } else {
//     noTone(BUZZER_PIN);
//     buzzerState = false;
//   }
// }

// void handleDoorState(){
//   if(doorOpen && (millis()-doorOpenTime > DOOR_AUTO_CLOSE)){
//     doorServo.write(SERVO_LOCKED_POS);
//     doorOpen = false;
//     Serial.println("Door auto-locked.");
//     sendSms("Door auto-locked.");
//     updateLcdDisplay();
//   }
// }

// // -------------------- SETUP --------------------
// void setup(){
//   Serial.begin(115200);
//   Wire.begin(I2C_SDA_PIN,I2C_SCL_PIN);
//   lcd.init();
//   lcd.backlight();
//   lcd.setCursor(0,0);
//   lcd.print("System Booting...");
//   delay(1500);

//   WiFi.begin(ssid,password);
//   lcd.setCursor(0,1);
//   lcd.print("Connecting Wi-Fi...");
//   while(WiFi.status()!=WL_CONNECTED){
//     delay(500);
//     Serial.print(".");
//   }
//   Serial.println("Wi-Fi Connected");
//   lcd.setCursor(0,1);
//   lcd.print("Wi-Fi Connected   ");

//   doorServo.attach(SERVO_PIN);
//   doorServo.write(SERVO_LOCKED_POS);

//   if(mpu.begin()!=0){
//     lcd.clear();
//     lcd.setCursor(0,0);
//     lcd.print("MPU-6050 ERROR!");
//     Serial.println("MPU-6050 NOT connected!");
//     while(1);
//   }
//   mpu.calcOffsets();

//   SPI.begin();
//   rfid.PCD_Init();

//   updateLcdDisplay();
//   Serial.println("System Ready.");
// }

// // -------------------- MAIN LOOP --------------------
// void loop(){
//   handleMotionSensor();
//   handleRfidReader();
//   handleAlarmState();
//   handleDoorState();
//   updateLcdDisplay();
// }