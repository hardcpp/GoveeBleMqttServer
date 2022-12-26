#!/usr/bin/env python
import asyncio;
import json;
import paho.mqtt.client as mqtt;
import GoveeBleLight;
import sys;
import getopt;
import time;
import signal;

SERVER_ZONE_ID: int = 1;
ADAPTER: str = None;
MQTT_SERVER: str = "192.168.10.170";
MQTT_PORT: int = 1883;
MQTT_USER: str = None;
MQTT_PASS: str = None;

# ////////////////////////////////////////////////////////////////////////////
# ////////////////////////////////////////////////////////////////////////////

CLIENTS         = {};
MESSAGE_QUEUE   = [];
RUNNING         = True;

# ////////////////////////////////////////////////////////////////////////////
# ////////////////////////////////////////////////////////////////////////////

# Entry point
async def main(argv):
    global SERVER_ZONE_ID;
    global ADAPTER;
    global CLIENTS;
    global MESSAGE_QUEUE;
    global RUNNING;

    l_Options, _ = getopt.getopt(argv,"hz:a:",["adapter=","zone="])
    for l_Option, l_Argument in l_Options:
        if l_Option == '-h':
            print('main.py -a <adapter> -z <zone>');
            sys.exit();

        elif l_Option in ("-a", "--adapter"):
            ADAPTER = l_Argument

        elif l_Option in ("-z", "--zone"):
            SERVER_ZONE_ID = l_Argument

    print("[Main] Starting with zone " + str(SERVER_ZONE_ID));
    if ADAPTER is not None:
        print("[Main] Starting with adapter " + ADAPTER);

    signal.signal(signal.SIGINT, Signal_OnSigInt);

    l_MqttClient = mqtt.Client();
    l_MqttClient.on_connect = Mqtt_OnConnect;
    l_MqttClient.on_message = Mqtt_OnMessage;

    if MQTT_USER != None and MQTT_PASS != None:
        l_MqttClient.username_pw_set(MQTT_USER, MQTT_PASS);

    l_MqttClient.connect(MQTT_SERVER, MQTT_PORT, 60);

    while RUNNING:
        try:
            if l_MqttClient.loop() != mqtt.MQTT_ERR_SUCCESS:
                print("[Main] Disconnected from Mqtt, trying to reconnect in 5 seconds...");
                time.sleep(5);

                if l_MqttClient.connect() == mqtt.MQTT_ERR_SUCCESS:
                    pass;

            while len(MESSAGE_QUEUE) > 0:
                l_Message   = MESSAGE_QUEUE.pop(0);
                l_Topic     = l_Message.topic;
                l_Prefix    = "goveeblemqtt/zone" + str(SERVER_ZONE_ID) + "/light/";
                l_Suffix    = "/command";

                if not l_Topic.startswith(l_Prefix) and not l_Topic.endwith(l_Suffix):
                    continue;

                l_DeviceID = l_Topic[len(l_Prefix):len(l_Topic)-len(l_Suffix)];
                l_Payload  = json.loads(l_Message.payload.decode("utf-8","ignore"));

                OnPayloadReceived(l_MqttClient, l_DeviceID, l_Payload);

        except:
            pass;

    print("[Main] Exiting...");

    for l_Client in CLIENTS:
        CLIENTS[l_Client].Close();

    sys.exit(0);

# ////////////////////////////////////////////////////////////////////////////
# ////////////////////////////////////////////////////////////////////////////

# On signal Int
def Signal_OnSigInt(p_Signal, p_Frame):
    global RUNNING;

    RUNNING = False;

    print("[Signal_OnSigInt] Exiting...");

# ////////////////////////////////////////////////////////////////////////////
# ////////////////////////////////////////////////////////////////////////////

# On Mqtt connect
def Mqtt_OnConnect(p_MqttClient, _, __, ___):
    l_Topic = "goveeblemqtt/zone" + str(SERVER_ZONE_ID) + "/light/+/command";

    print("[Mqtt_OnConnect] Connected to Mqtt broker")
    print("[Mqtt_OnConnect] Subscribing to topic: " + l_Topic);

    p_MqttClient.subscribe(l_Topic)
# On Mqtt message
def Mqtt_OnMessage(p_MqttClient, _, p_Message):
    global MESSAGE_QUEUE;
    MESSAGE_QUEUE.append(p_Message);

# ////////////////////////////////////////////////////////////////////////////
# ////////////////////////////////////////////////////////////////////////////

def OnPayloadReceived(p_MqttClient, p_DeviceID, p_Paypload):
    global CLIENTS;
    global MESSAGE_QUEUE;

    l_RequestedDeviceID = p_DeviceID;
    l_Device            = None;

    try:
        p_DeviceID = ':'.join(p_DeviceID[i:i+2] for i in range(0, len(p_DeviceID), 2));

        if not p_DeviceID in CLIENTS:
            CLIENTS[p_DeviceID] = GoveeBleLight.Client(p_DeviceID, p_MqttClient, "goveeblemqtt/zone" + str(SERVER_ZONE_ID) + "/light/" + l_RequestedDeviceID + "/state", ADAPTER);
            time.sleep(2);

        l_Device        = CLIENTS[p_DeviceID];
        l_ExpectedState = 1 if p_Paypload["state"] == "ON" else 0;

        if l_Device.State != l_ExpectedState:
            l_Device.SetPower(l_ExpectedState);

        if "brightness" in p_Paypload:
            l_Device.SetBrightness(p_Paypload["brightness"] / 255);

        if "color" in p_Paypload:
            l_R = p_Paypload["color"]["r"];
            l_G = p_Paypload["color"]["g"];
            l_B = p_Paypload["color"]["b"];

            if l_Device.R != l_R or l_Device.G != l_G or l_Device.B != l_B:
                l_Device.SetColorRGB(l_R, l_G, l_B);

        print(p_DeviceID + " " + str(p_Paypload));

    except Exception as l_Exception:
        print(f"[OnPayloadReceived] OnPayloadReceived: Something Bad happened: {l_Exception}")

# ////////////////////////////////////////////////////////////////////////////
# ////////////////////////////////////////////////////////////////////////////

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]));