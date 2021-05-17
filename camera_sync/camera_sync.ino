/***
 * BpodAcademy Camera Sync Teensy Firmware
 * 
 * Communicates with a computer running BpodAcademy 
 * to synchronize cameras with Bpod behavioral data.
 * -- Confirms connection with BpodAcademy
 * -- Returns the teensy timestamp on command
 * -- Relays TTL pulses from Bpods to BpodAcademy
 *    - TTLs are recorded in video timestamp files
 * 
 * Note:
 * Teensy 3.2 USB serial is always 12 MBit, regardless of Baud Rate set here.
 * 
 * Public variables:
 * connected_to_bpod_academy: bool, indicates connected to BpodAcadmey
 * current_time: unsigned long, the current time (according to millis)
 * channel_start_time: array of unsigned longs, start time for each TTL
 * channel_on: array of bools, indicating whether channel is active
 * 
 * Serial input:
 * 'A' : connect to BpodAcademy
 *    -- return confirmation code
 * 'Z' : disconnect from BpodAcademy
 *    -- return confirmation code
 * 'S' : start recording for current channel
 *    -- return starting timestamp
 * 'E' : end recording for current channel   
 *    -- return ending timestamp
 * 'Y' : reboot (only if not connected to BpodAcademy)
 * 
 * Serial output:
 * On TLL input (change from high -> low or low -> high),
 *    return ['T', channel, state (low = 0, high = 1), time (current time - channel start time)]
 * 
 ***/

// global variables:
bool connected_to_bpod_academy = false;
unsigned long current_time = 0;
unsigned long channel_start_time[13];
bool channel_on[13];

void write_short(int x) {

  Serial.write(x);
  Serial.write(x >> 8);

}

void write_long(unsigned long x) {

  Serial.write(x);
  Serial.write(x >> 8);
  Serial.write(x >> 16);
  Serial.write(x >> 24);
  
}

void connect_to_bpod_academy() {

  connected_to_bpod_academy = true;

  Serial.print('A');
  Serial.flush();
  digitalWrite(13, HIGH);
  
}

void disconnect_from_bpod_academy() {

  for (int i = 0; i < 13; i++) {

    channel_on[i] = false;
    channel_start_time[i] = 0;
    
  }

  connected_to_bpod_academy = false;
  
  Serial.print('Z');
  Serial.flush();
  digitalWrite(13, LOW);
  
}

void activate_channel(int channel) {

  channel_on[channel] = true;
  channel_start_time[channel] = current_time;
  
  Serial.print('S');
  write_short(channel);
  Serial.write(channel_on[channel]);
  write_long(current_time);
  Serial.flush();
  
}


void deactivate_channel(int channel) {

  channel_on[channel] = false;
  channel_start_time[channel] = current_time;
  
  Serial.print('E');
  write_short(channel);
  Serial.write(channel_on[channel]);
  write_long(current_time);
  Serial.flush();
  
}

void on_ttl(int channel) {

  if (channel_on[channel]) {
    
    int state = digitalRead(channel);
    unsigned long ttl_time = current_time - channel_start_time[channel];
    
    Serial.print('T');
    write_short(channel);
    Serial.write(state);
    write_long(ttl_time);
    Serial.flush();
    
  }
  
}

void interrupt_ttl0() {
  on_ttl(0);
}

void interrupt_ttl1() {
  on_ttl(1);
}

void interrupt_ttl2() {
  on_ttl(2);
}

void interrupt_ttl3() {
  on_ttl(3);
}

void interrupt_ttl4() {
  on_ttl(4);
}

void interrupt_ttl5() {
  on_ttl(5);
}

void interrupt_ttl6() {
  on_ttl(6);
}

void interrupt_ttl7() {
  on_ttl(7);
}

void interrupt_ttl8() {
  on_ttl(8);
}

void interrupt_ttl9() {
  on_ttl(9);
}

void interrupt_ttl10() {
  on_ttl(10);
}

void interrupt_ttl11() {
  on_ttl(11);
}

void interrupt_ttl12() {
  on_ttl(12);
}

typedef void (*FuncPtr)(void);
FuncPtr interrupt_functions[] = {&interrupt_ttl0,
                                 &interrupt_ttl1,
                                 &interrupt_ttl2,
                                 &interrupt_ttl3,
                                 &interrupt_ttl4,
                                 &interrupt_ttl5,
                                 &interrupt_ttl6,
                                 &interrupt_ttl7,
                                 &interrupt_ttl8,
                                 &interrupt_ttl9,
                                 &interrupt_ttl10,
                                 &interrupt_ttl11,
                                 &interrupt_ttl12};

void setup() {

  Serial.begin(9600);

  // define 13 (internal LED) as output
  pinMode(13, OUTPUT);

  // define channels 0-12 as inputs (using internal pulldown resistor)
  // attach interrupt to return timestamps upon transition
  for (int i=0; i<13; i++) {

    pinMode(i, INPUT_PULLDOWN);
    attachInterrupt(digitalPinToInterrupt(i), interrupt_functions[i], CHANGE);
    channel_start_time[i] = 0;
    channel_on[i] = false;
    
  }

  
  
}


void loop() {

  current_time = millis();

  while (Serial.available() > 0) {

    unsigned int cmd = Serial.read();

    if (connected_to_bpod_academy) {

      if (cmd == 'Z') {

        disconnect_from_bpod_academy();
        
      } else if (cmd == 'S') {

        int channel = Serial.read();
        activate_channel(channel);      
        
      } else if (cmd == 'E') {

        int channel = Serial.read();
        deactivate_channel(channel);
        
      } else if (cmd == 'A') {

        disconnect_from_bpod_academy();
        delay(1000);
        connect_to_bpod_academy();
        
      }
      
    } else {

      if (cmd == 'A') {
        
        connect_to_bpod_academy();
      
      } else if (cmd == 'Y'){
       
        _reboot_Teensyduino_();
        
      }
    
    }

  }

}
