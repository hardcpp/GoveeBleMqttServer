#!/usr/bin/env python
import asyncio;
import json;
import threading;
import time;
import math;

from enum import IntEnum;
from bleak import BleakClient;

# ////////////////////////////////////////////////////////////////////////////
# ////////////////////////////////////////////////////////////////////////////

UUID_CONTROL_CHARACTERISTIC = '00010203-0405-0607-0809-0a0b0c0d2b11'

# ////////////////////////////////////////////////////////////////////////////
# ////////////////////////////////////////////////////////////////////////////

class ELedCommand(IntEnum):
    SetPower        = 0x01
    SetBrightness   = 0x04
    SetColor        = 0x05

class ELedMode(IntEnum):
    Manual     = 0x02
    Microphone = 0x06
    Scenes     = 0x05
    Manual2    = 0x0D
    Segment    = 0x15

class EControlMode(IntEnum):
    Color       = 0x01
    Temperature = 0x02

def convert_K_to_RGB(colour_temperature):
    """
    Converts from K to RGB, algorithm courtesy of
    http://www.tannerhelland.com/4435/convert-temperature-rgb-algorithm-code/
    """
    #range check
    if colour_temperature < 1000:
        colour_temperature = 1000
    elif colour_temperature > 40000:
        colour_temperature = 40000

    tmp_internal = colour_temperature / 100.0

    # red
    if tmp_internal <= 66:
        red = 255
    else:
        tmp_red = 329.698727446 * math.pow(tmp_internal - 60, -0.1332047592)
        if tmp_red < 0:
            red = 0
        elif tmp_red > 255:
            red = 255
        else:
            red = tmp_red

    # green
    if tmp_internal <=66:
        tmp_green = 99.4708025861 * math.log(tmp_internal) - 161.1195681661
        if tmp_green < 0:
            green = 0
        elif tmp_green > 255:
            green = 255
        else:
            green = tmp_green
    else:
        tmp_green = 288.1221695283 * math.pow(tmp_internal - 60, -0.0755148492)
        if tmp_green < 0:
            green = 0
        elif tmp_green > 255:
            green = 255
        else:
            green = tmp_green

    # blue
    if tmp_internal >=66:
        blue = 255
    elif tmp_internal <= 19:
        blue = 0
    else:
        tmp_blue = 138.5177312231 * math.log(tmp_internal - 10) - 305.0447927307
        if tmp_blue < 0:
            blue = 0
        elif tmp_blue > 255:
            blue = 255
        else:
            blue = tmp_blue

    return int(red), int(green), int(blue);

# ////////////////////////////////////////////////////////////////////////////
# ////////////////////////////////////////////////////////////////////////////

class Client:
    # Constructor
    def __init__(self, p_DeviceID, p_Model, p_MqttClient, p_MqttTopic, p_Adapter):
        self.ControlMode        = EControlMode.Color;
        self.State              = 0;
        self.Brightness         = 1;
        self.Segment            = -1;
        self.Temperature        = 4000;
        self.R                  = 255;
        self.G                  = 255;
        self.B                  = 255;

        self._DeviceID          = p_DeviceID;
        self._Model             = p_Model;
        self._Client            = None;
        self._Adapter           = p_Adapter;
        self._Reconnect         = 0;
        self._MqttClient        = p_MqttClient;
        self._MqttTopic         = p_MqttTopic;
        self._DirtyState        = False;
        self._DirtyBrightness   = False;
        self._DirtyColor        = False;
        self._LastSent          = time.time();
        self._PingRoll          = 0;
        self._ThreadCond        = True;
        self._Thread            = threading.Thread(target= self._ThreadStarter);

        self._Thread.start();
    # Destructor
    def __del__(self):
        self.Close();

    # ////////////////////////////////////////////////////////////////////////////
    # ////////////////////////////////////////////////////////////////////////////

    # Properly close the client
    def Close(self):
        if self._Thread is None:
            return;

        print("[GoveeBleLight.Client::Close] Closing device " + self._DeviceID + "...");

        try:
            self._ThreadCond = False;
            self._Thread.join(10);
        except:
            pass;

        self._Thread = None;

    # ////////////////////////////////////////////////////////////////////////////
    # ////////////////////////////////////////////////////////////////////////////

    def SetPower(self, p_State):
        if not isinstance(p_State, int) or p_State < 0 or p_State > 1:
           raise ValueError('Invalid command')

        self.State = 1 if p_State else 0;
        self._DirtyState = True;

    def SetBrightness(self, p_Value):
        if not 0 <= float(p_Value) <= 1:
            raise ValueError(f'SetBrightness: Brightness out of range: {p_Value}')

        self.Brightness         = p_Value;
        self._DirtyBrightness   = True;

    def SetSegment(self, p_Segment):
        if p_Segment == -1 or p_Segment == 0:
            self.Segment = -1;
        else:
            self.Segment = p_Segment;

    def SetColorTempMired(self, p_Value):
        l_ColorTempK = 1000000 / p_Value;

        self.ControlMode = EControlMode.Temperature;
        self.Temperature = l_ColorTempK;
        self._DirtyColor = True;

    def SetColorRGB(self, p_R, p_G, p_B):
        if not isinstance(p_R, int) or p_R < 0 or p_R > 255:
           raise ValueError(f'SetColorRGB: p_R out of range {p_R}');
        if not isinstance(p_G, int) or p_G < 0 or p_G > 255:
           raise ValueError(f'SetColorRGB: p_G out of range {p_G}');
        if not isinstance(p_B, int) or p_B < 0 or p_B > 255:
           raise ValueError(f'SetColorRGB: p_B out of range {p_B}');

        self.ControlMode    = EControlMode.Color;
        self.R              = p_R;
        self.G              = p_G;
        self.B              = p_B;
        self._DirtyColor    = True;

    # ////////////////////////////////////////////////////////////////////////////
    # ////////////////////////////////////////////////////////////////////////////

    # Thread main aync coroutine
    async def _ThreadCoroutine(self):
        while self._ThreadCond:
            try:
                if not await self._Connect():
                    time.sleep(2);
                    continue;

                l_Changed = True;

                if self._DirtyState:
                    if not await self._Send_SetPower(self.State):
                        time.sleep(1);
                        continue;

                    self._DirtyState = False;
                elif self._DirtyBrightness:
                    if not await self._Send_SetBrightness(self.Brightness):
                        time.sleep(1);
                        continue;

                    self._DirtyBrightness = False;
                elif self._DirtyColor:
                    if not await self._Send_SetColor():
                        time.sleep(1);
                        continue;

                    self._DirtyColor = False;
                else:
                    l_Changed = False;

                    # Keep alive
                    if (time.time() - self._LastSent) >= 1:
                        l_AsyncRes = False;
                        self._PingRoll += 1;

                        if self._PingRoll % 3 == 0 or self.State == 0:
                            l_AsyncRes = await self._Send_SetPower(self.State);
                        elif self._PingRoll % 3 == 1:
                            l_AsyncRes = await self._Send_SetBrightness(self.Brightness);
                        elif self._PingRoll % 3 == 2:
                            l_AsyncRes = await self._Send_SetColor();

                    time.sleep(0.1);
                    continue;

                if l_Changed:
                    print(self.BuildMqttPayload());
                    self._MqttClient.publish(self._MqttTopic, self.BuildMqttPayload());

                time.sleep(0.01);

            except Exception as l_Exception:
                print(f"[GoveeBleLight.Client::_ThreadCoroutine] Error: {l_Exception}");

                try:
                    if self._Client is not None:
                        await self._Client.disconnect();
                except Exception:
                    pass;

                self._Client = None;

                time.sleep(2);

        try:
            if self._Client is not None:
                print("[GoveeBleLight.Client::_ThreadCoroutine] Disconnecting device " + self._DeviceID);
                await self._Client.disconnect();

        except Exception:
            pass;

        self._Client = None;

    # Thread starter function
    def _ThreadStarter(self):
        while self._ThreadCond:
            print("[GoveeBleLight.Client::_ThreadStarter] Starting device " + self._DeviceID + " event loop...");

            time.sleep(0.5);

            l_ThreadCoroutine = asyncio.new_event_loop();
            asyncio.set_event_loop(l_ThreadCoroutine);
            l_ThreadCoroutine.run_until_complete(self._ThreadCoroutine());
            l_ThreadCoroutine.close();

    # ////////////////////////////////////////////////////////////////////////////
    # ////////////////////////////////////////////////////////////////////////////

    # Handle connect/reconnect
    async def _Connect(self):
        if self._Client != None and self._Client.is_connected:
            return True;

        print("[GoveeBleLight.Client::Connect] re/connecting to device " + self._DeviceID);

        try:
            if self._Client is not None:
                await self._Client.disconnect();

        except Exception:
            pass;

        self._Client = None;

        try:
            if self._Adapter is not None:
                self._Client = BleakClient(self._DeviceID, adapter= self._Adapter);
            else:
                self._Client = BleakClient(self._DeviceID);

            await self._Client.connect();
            self._Reconnect = 0;

            print("[GoveeBleLight.Client::Connect] Connected to device " + self._DeviceID);

            return self._Client.is_connected;

        except Exception as l_Exception:
            self._Client = None;
            print(f"[GoveeBleLight.Client::_Connect] Error: {l_Exception}");

        return False;

    # ////////////////////////////////////////////////////////////////////////////
    # ////////////////////////////////////////////////////////////////////////////

    async def _Send_SetPower(self, p_State):
        if not isinstance(p_State, int) or p_State < 0 or p_State > 1:
           raise ValueError('Invalid command')

        try:
            return await self._Send(ELedCommand.SetPower, [1 if p_State else 0])

        except Exception as l_Exception:
             print(f"[GoveeBleLight.Client::_Send_SetPower] Error: {l_Exception}");

        return False;

    async def _Send_SetBrightness(self, p_Value):
        if not 0 <= float(p_Value) <= 1:
            raise ValueError(f'SetBrightness: Brightness out of range: {p_Value}')

        l_Brightness = round(p_Value * 0xFF);

        if self._Model == "H6008" or self._Model == "H613A" self._Model == "H613D" or self._Model == "H6172":
            l_Brightness = int(p_Value * 100);

        try:
            return await self._Send(ELedCommand.SetBrightness, [l_Brightness]);

        except Exception as l_Exception:
             print(f"[GoveeBleLight.Client::_Send_SetBrightness] Error: {l_Exception}");

        return False;

    async def _Send_SetColor(self):
        l_R = self.R;
        l_G = self.G;
        l_B = self.B;

        l_TK = 0
        l_WR = 0;
        l_WG = 0;
        l_WB = 0;

        if self.ControlMode == EControlMode.Temperature:
            l_R  = l_G = l_B = 0xFF;
            l_TK = int(self.Temperature);

        if not isinstance(l_R, int) or l_R < 0 or l_R > 255:
           raise ValueError(f'SetColorRGB: l_R out of range {l_R}');
        if not isinstance(l_G, int) or l_G < 0 or l_G > 255:
           raise ValueError(f'SetColorRGB: l_G out of range {l_G}');
        if not isinstance(l_B, int) or l_B < 0 or l_B > 255:
           raise ValueError(f'SetColorRGB: l_B out of range {l_B}');

        l_LedMode = ELedMode.Manual;

        try:
            if self._Model == "H6008" or self._Model == "H613A" or self._Model == "H613D":
                l_LedMode = ELedMode.Manual2;

                return await self._Send(ELedCommand.SetColor, [l_LedMode, l_R, l_G, l_B, (l_TK >> 8) & 0xFF, l_TK & 0xFF, l_WR, l_WG, l_WB]);
            elif self._Model == "H6172":
                l_LedMode = ELedMode.Segment;

                return await self._Send(ELedCommand.SetColor, [l_LedMode, 0x01, l_R, l_G, l_B, (l_TK >> 8) & 0xFF, l_TK & 0xFF, l_WR, l_WG, l_WB, (self.Segment >> 8) & 0xFF, self.Segment & 0xFF]);
            else:
                # Todo figure out WW control
                return await self._Send(ELedCommand.SetColor, [l_LedMode, l_R, l_G, l_B]);

        except Exception as l_Exception:
             print(f"[GoveeBleLight.Client::_Send_SetColor] Error: {l_Exception}");

        return False;

    # ////////////////////////////////////////////////////////////////////////////
    # ////////////////////////////////////////////////////////////////////////////

    def BuildMqttPayload(self):
        if self.ControlMode == EControlMode.Color:
            return json.dumps({
                "state":        "ON" if self.State == 1 else "OFF",
                "color": {
                    "r": self.R,
                    "g": self.G,
                    "b": self.B
                },
                "brightness":   round(self.Brightness * 255)
            });
        elif self.ControlMode == EControlMode.Temperature:
            l_TempColorR, l_TempColorG, l_TempColorB = convert_K_to_RGB(self.Temperature);

            return json.dumps({
                "state":        "ON" if self.State == 1 else "OFF",
                "brightness":   round(self.Brightness * 255),
                "color": {
                    "r": l_TempColorR,
                    "g": l_TempColorG,
                    "b": l_TempColorB
                },
                "color_temp":   int(1000000 / self.Temperature)
            });

    # ////////////////////////////////////////////////////////////////////////////
    # ////////////////////////////////////////////////////////////////////////////

    async def _Send(self, p_CMD, p_Payload):
        if not isinstance(p_CMD, int):
           raise ValueError('[GoveeBleLight.Client::_Send] Invalid command');
        if not isinstance(p_Payload, bytes) and not (isinstance(p_Payload, list) and all(isinstance(x, int) for x in p_Payload)):
            raise ValueError('[GoveeBleLight.Client::_Send] Invalid payload');
        if len(p_Payload) > 17:
            raise ValueError('[GoveeBleLight.Client::_Send] Payload too long');

        p_CMD       = p_CMD & 0xFF;
        p_Payload   = bytes(p_Payload);

        l_Frame  = bytes([0x33, p_CMD]) + bytes(p_Payload);
        l_Frame += bytes([0] * (19 - len(l_Frame)));

        l_Checksum = 0;
        for l_Byte in l_Frame:
            l_Checksum ^= l_Byte;

        l_Frame += bytes([l_Checksum & 0xFF]);

        try:
            await self._Client.write_gatt_char(UUID_CONTROL_CHARACTERISTIC, l_Frame);
            self._LastSent = time.time();

            return True;

        except Exception as l_Exception:
            print(f"[GoveeBleLight.Client::_Send] Error: {l_Exception}");

            try:
                if self._Client is not None:
                    print("[GoveeBleLight.Client::_Send] Disconnecting device " + self._DeviceID);
                    await self._Client.disconnect();

            except:
                pass;

            self._Reconnect += 1;
            self._Client     = None;

        return False;
