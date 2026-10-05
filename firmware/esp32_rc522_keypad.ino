// Workstreams G + H: demo keypad and RC522 serial event source.
// RC522 is 3.3 V ONLY. This firmware emits lines consumed by nfc_payment.py.
#include <SPI.h>
#include <MFRC522.h>
#include <Keypad.h>

#define RC522_SS_PIN 5
#define RC522_RST_PIN 22
MFRC522 rfid(RC522_SS_PIN, RC522_RST_PIN);

const byte ROWS = 4;
const byte COLS = 3;
char keys[ROWS][COLS] = {
  {'1','2','3'}, {'4','5','6'}, {'7','8','9'}, {'*','0','#'}
};
byte rowPins[ROWS] = {13, 14, 25, 26};
byte colPins[COLS] = {27, 32, 33};
Keypad keypad = Keypad(makeKeymap(keys), rowPins, colPins, ROWS, COLS);

void setup() {
  Serial.begin(115200);
  SPI.begin(18, 19, 23, RC522_SS_PIN); // SCK, MISO, MOSI, SS
  rfid.PCD_Init();
}

void loop() {
  char key = keypad.getKey();
  if (key) {
    Serial.print("KEYPAD:");
    Serial.println(key);
  }

  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) return;
  Serial.print("NFC_TAG:");
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) Serial.print('0');
    Serial.print(rfid.uid.uidByte[i], HEX);
  }
  Serial.println();
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
  delay(250);
}
