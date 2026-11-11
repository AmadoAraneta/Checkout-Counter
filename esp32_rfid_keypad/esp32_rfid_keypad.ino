/*
  Checkout Counter - ESP32 RFID/NFC + 4x3 Keypad

  Hardware:
    ESP32 Type-C development board, 30 pins
    RC522 RFID reader over VSPI
    4x3 matrix membrane keypad

  RC522 wiring:
    3.3V -> 3.3V
    GND  -> GND
    SCK  -> GPIO18
    MOSI -> GPIO23
    MISO -> GPIO19
    SDA  -> GPIO5  (SS / CS)
    RST  -> GPIO27
    IRQ  -> not connected

  Keypad wiring:
    R1 -> GPIO13
    R2 -> GPIO14
    R3 -> GPIO16
    R4 -> GPIO17
    C1 -> GPIO25
    C2 -> GPIO26
    C3 -> GPIO32

  Serial protocol:
    One JSON event per line at 115200 baud.
    Examples:
      {"event":"ready"}
      {"event":"card_detected","uid":"04-A3-7B-91"}
      {"event":"key_pressed","key":"5"}
*/

#include <SPI.h>
#include <MFRC522.h>
#include <Keypad.h>

// RC522 pins
constexpr byte RFID_SS_PIN = 5;
constexpr byte RFID_RST_PIN = 27;
constexpr byte RFID_SCK_PIN = 18;
constexpr byte RFID_MISO_PIN = 19;
constexpr byte RFID_MOSI_PIN = 23;

// Keypad pins
const byte ROWS = 4;
const byte COLS = 3;
byte rowPins[ROWS] = {13, 14, 16, 17};
byte colPins[COLS] = {25, 26, 32};

char keyMap[ROWS][COLS] = {
  {'1', '2', '3'},
  {'4', '5', '6'},
  {'7', '8', '9'},
  {'*', '0', '#'}
};

MFRC522 rfid(RFID_SS_PIN, RFID_RST_PIN);
Keypad keypad = Keypad(makeKeymap(keyMap), rowPins, colPins, ROWS, COLS);

String lastUid = "";
unsigned long lastCardEventAt = 0;
const unsigned long CARD_EVENT_COOLDOWN_MS = 2000;

void printReady() {
  Serial.println(F("{\"event\":\"ready\"}"));
}

void printKeyEvent(char key) {
  Serial.print(F("{\"event\":\"key_pressed\",\"key\":\""));
  Serial.print(key);
  Serial.println(F("\"}"));
}

String uidToString(MFRC522::Uid *uid) {
  String value = "";

  for (byte i = 0; i < uid->size; i++) {
    if (uid->uidByte[i] < 0x10) {
      value += "0";
    }
    value += String(uid->uidByte[i], HEX);
    if (i < uid->size - 1) {
      value += "-";
    }
  }

  value.toUpperCase();
  return value;
}

void printCardEvent(const String &uid) {
  Serial.print(F("{\"event\":\"card_detected\",\"uid\":\""));
  Serial.print(uid);
  Serial.println(F("\"}"));
}

void setup() {
  Serial.begin(115200);
  delay(300);

  // Explicitly use the ESP32 VSPI pins listed above.
  SPI.begin(RFID_SCK_PIN, RFID_MISO_PIN, RFID_MOSI_PIN, RFID_SS_PIN);
  rfid.PCD_Init();
  delay(50);

  printReady();
}

void loop() {
  // Read keypad events. The dashboard/backend can use these for PIN entry.
  char key = keypad.getKey();
  if (key) {
    printKeyEvent(key);
  }

  // Detect a newly presented RFID card/tag.
  if (!rfid.PICC_IsNewCardPresent()) {
    delay(5);
    return;
  }

  if (!rfid.PICC_ReadCardSerial()) {
    delay(5);
    return;
  }

  String uid = uidToString(&rfid.uid);
  unsigned long now = millis();

  // Avoid sending repeated events while the same card remains on the reader.
  if (uid != lastUid || now - lastCardEventAt >= CARD_EVENT_COOLDOWN_MS) {
    printCardEvent(uid);
    lastUid = uid;
    lastCardEventAt = now;
  }

  // Stop communication with the card before the next scan.
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
  delay(50);
}
