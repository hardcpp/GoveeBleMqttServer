import asyncio;
import json;
import threading;
import time;

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

# ////////////////////////////////////////////////////////////////////////////
# ////////////////////////////////////////////////////////////////////////////

class Client:
    def __init__(self, p_DeviceID, p_MqttClient, p_MqttTopic, p_Adapter):

        self.State              = 0;
        self.Brightness         = 1;
        self.R                  = 255;
        self.G                  = 255;
        self.B                  = 255;

        self._DeviceID          = p_DeviceID;
        self._Client            = None;
        self._Adapter           = p_Adapter;
        self._Reconnect         = 0;
        self._MqttClient        = p_MqttClient;
        self._MqttTopic         = p_MqttTopic;
        self._DirtyState        = False;
        self._DirtyBrightness   = False;
        self._DirtyRGB          = False;
        self._LastSent          = time.time();

        threading.Thread(target=self._ThreadStarter).start();

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

    def SetColorRGB(self, p_R, p_G, p_B):
        if not isinstance(p_R, int) or p_R < 0 or p_R > 255:
           raise ValueError(f'SetColorRGB: p_R out of range {p_R}');
        if not isinstance(p_G, int) or p_G < 0 or p_G > 255:
           raise ValueError(f'SetColorRGB: p_G out of range {p_G}');
        if not isinstance(p_B, int) or p_B < 0 or p_B > 255:
           raise ValueError(f'SetColorRGB: p_B out of range {p_B}');

        self.R          = p_R;
        self.G          = p_G;
        self.B          = p_B;
        self._DirtyRGB  = True;

    # ////////////////////////////////////////////////////////////////////////////
    # ////////////////////////////////////////////////////////////////////////////

    async def _ThreadCoroutine(self):
        while 1:
            try:
                if not await self._Connect():
                    time.sleep(1);
                    continue;

                l_Changed = True;

                if not self._DirtyState and not self._DirtyBrightness and not self._DirtyRGB and (time.time() - self._LastSent) >= 1:
                    if not await self._Send_SetPower(self.State):
                        time.sleep(1);
                        continue;

                    #print("[GoveeBleLight.Client::_ThreadCoroutine] keep alive!");

                elif self._DirtyState:
                    if not await self._Send_SetPower(self.State):
                        time.sleep(1);
                        continue;

                    self._DirtyState = False;
                elif self._DirtyBrightness:
                    if not await self._Send_SetBrightness(self.Brightness):
                        time.sleep(1);
                        continue;

                    self._DirtyBrightness = False;
                elif self._DirtyRGB:
                    if not await self._Send_SetColorRGB(self.R, self.G, self.B):
                        time.sleep(1);
                        continue;

                    self._DirtyRGB = False;
                else:
                    l_Changed = False;

                if l_Changed:
                    self._MqttClient.publish(self._MqttTopic, self.BuildMqttPayload());

                time.sleep(0.01);

            except Exception:
                time.sleep(1);

    def _ThreadStarter(self):
        l_ThreadCoroutine = asyncio.new_event_loop()
        asyncio.set_event_loop(l_ThreadCoroutine)
        l_ThreadCoroutine.run_until_complete(self._ThreadCoroutine())
        l_ThreadCoroutine.close()

    # ////////////////////////////////////////////////////////////////////////////
    # ////////////////////////////////////////////////////////////////////////////

    async def _Connect(self):
        if self._Client and self._Client.is_connected:
            return True;

        print("[GoveeBleLight.Client::Connect] re/connecting to device " + self._DeviceID);

        try:
            if self._Client is not None:
                await self._Client.disconnect();
                self._Client = None;
        except Exception:
            pass;

        if self._Adapter is not None:
            self._Client = BleakClient(self._DeviceID, adapter= self._Adapter);
        else:
            self._Client = BleakClient(self._DeviceID);

        await self._Client.connect();
        self._Reconnect = 0;

        return self._Client.is_connected;

    # ////////////////////////////////////////////////////////////////////////////
    # ////////////////////////////////////////////////////////////////////////////

    async def _Send_SetPower(self, p_State):
        if not isinstance(p_State, int) or p_State < 0 or p_State > 1:
           raise ValueError('Invalid command')

        try:
            return await self._Send(ELedCommand.SetPower, [1 if p_State else 0])

        except Exception as l_Exception:
             print(f"[GoveeBleLight.Client::SetPower] Error: {l_Exception}");

        return False;

    async def _Send_SetBrightness(self, p_Value):
        if not 0 <= float(p_Value) <= 1:
            raise ValueError(f'SetBrightness: Brightness out of range: {p_Value}')

        try:
            return await self._Send(ELedCommand.SetBrightness, [round(p_Value * 0xFF)]);

        except Exception as l_Exception:
             print(f"[GoveeBleLight.Client::SetBrightness] Error: {l_Exception}");

        return False;

    async def _Send_SetColorRGB(self, p_R, p_G, p_B):
        if not isinstance(p_R, int) or p_R < 0 or p_R > 255:
           raise ValueError(f'SetColorRGB: p_R out of range {p_R}');
        if not isinstance(p_G, int) or p_G < 0 or p_G > 255:
           raise ValueError(f'SetColorRGB: p_G out of range {p_G}');
        if not isinstance(p_B, int) or p_B < 0 or p_B > 255:
           raise ValueError(f'SetColorRGB: p_B out of range {p_B}');

        try:
            return await self._Send(ELedCommand.SetColor, [ELedMode.Manual, p_R, p_G, p_B]);

        except Exception as l_Exception:
             print(f"[GoveeBleLight.Client::SetColorRGB] Error: {l_Exception}");

        return False;

    # ////////////////////////////////////////////////////////////////////////////
    # ////////////////////////////////////////////////////////////////////////////

    def BuildMqttPayload(self):
        return json.dumps({
            "state":        "ON" if self.State == 1 else "OFF",
            "color": {
                "r": self.R,
                "g": self.G,
                "b": self.B
            },
            "brightness":   round(self.Brightness * 255)
        });

    # ////////////////////////////////////////////////////////////////////////////
    # ////////////////////////////////////////////////////////////////////////////

    async def _Send(self, p_CMD, p_Payload):
        if not isinstance(p_CMD, int):
           raise ValueError('Invalid command');
        if not isinstance(p_Payload, bytes) and not (isinstance(p_Payload, list) and all(isinstance(x, int) for x in p_Payload)):
            raise ValueError('Invalid payload');
        if len(p_Payload) > 17:
            raise ValueError('Payload too long');

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

        except:
            if self._Reconnect > 0:
                return False;

            self._Reconnect += 1;

            return await self._Send(p_CMD, p_Payload);