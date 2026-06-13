# Robot ESP32-C3 with OLED Eyes, Servo Movement and Touch Control

This project is a small interactive robot based on an **ESP32-C3 Super Mini**.  
It uses an OLED display to show animated robot eyes, a servo motor to move the head, and a touch sensor to control some robot behaviors.

The robot can display expressive animated eyes, show basic weather information, move its head using a servo motor, and react to touch input.

## Features

- Animated robot eyes on OLED display
- Smooth eye transitions and expressive movements
- Servo motor head movement
- Touch sensor interaction
- Weather display with today and tomorrow forecast
- Time-based behavior management
- Designed for ESP32-C3 Super Mini
- Written in MicroPython

## Hardware Used

- ESP32-C3 Super Mini
- SSD1306 OLED display, 128x64, I2C
- SG90 or compatible micro servo motor
- TTP223 capacitive touch sensor
- Jumper wires

## Basic Wiring

### OLED Display SSD1306

| OLED Pin | ESP32-C3 Pin |
|---|---|
| VCC | 3.3V |
| GND | GND |
| SDA | GPIO 5 |
| SCL | GPIO 6 |

### Servo Motor

| Servo Wire | Connection |
|---|---|
| Signal | Servo control GPIO (4) |
| VCC | 5V |
| GND | Common GND with ESP32 |

### TTP223 Touch Sensor

| TTP223 Pin | ESP32-C3 Pin |
|---|---|
| VCC | 3.3V (PIN 21) |
| GND | GND |
| OUT | Touch input GPIO (20) |

## Software Requirements

- MicroPython installed on the ESP32-C3
- A tool to upload files to the board, for example:
  - Thonny IDE
  - ampy
  - mpremote
  - uPyCraft
  - ArduinoLab for Micropython

Required files:

```text
main.py
modern_eyes.py
ssd1306.py
