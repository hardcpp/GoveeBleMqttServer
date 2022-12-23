import asyncio;
import json;
import paho.mqtt.client as mqtt;
import GoveeBleLight;
import sys, getopt

SERVER_ZONE_ID: int = 1;
ADAPTER: str = None;
MQTT_SERVER: str = "192.168.10.170";
MQTT_PORT: int = 1883;
MQTT_USER: str = None;
MQTT_PASS: str = None;

# ////////////////////////////////////////////////////////////////////////////
# ////////////////////////////////////////////////////////////////////////////

DEVICES = {};
MESSAGE_QUEUE = [];

# ////////////////////////////////////////////////////////////////////////////
# ////////////////////////////////////////////////////////////////////////////

# Entry point
async def main(argv):
    global SERVER_ZONE_ID;
    global ADAPTER;

    l_Options, _ = getopt.getopt(argv,"hz:a:",["adapter=","zone="])
    for l_Option, l_Argument in l_Options:
        if l_Option == '-h':
            print('main.py -a <adapter> -z <zone>');
            sys.exit();

        elif l_Option in ("-a", "--adapter"):
            ADAPTER = l_Argument

        elif l_Option in ("-z", "--zone"):
            SERVER_ZONE_ID = l_Argument

    print("Starting with zone " + str(SERVER_ZONE_ID));
    if ADAPTER is not None:
        print("Starting with adapter " + ADAPTER);

    l_MqttClient = mqtt.Client();
    l_MqttClient.on_connect = Mqtt_OnConnect;
    l_MqttClient.on_message = Mqtt_OnMessage;

    if MQTT_USER != None and MQTT_PASS != None:
        l_MqttClient.username_pw_set(MQTT_USER, MQTT_PASS);

    l_MqttClient.connect(MQTT_SERVER, MQTT_PORT, 60);

    while 1:
        l_MqttClient.loop();

        while len(MESSAGE_QUEUE) > 0:
            l_Message   = MESSAGE_QUEUE.pop(0);
            l_Topic     = l_Message.topic;
            l_Prefix    = "goveeblemqtt/zone" + str(SERVER_ZONE_ID) + "/light/";
            l_Suffix    = "/command";

            if not l_Topic.startswith(l_Prefix) and not l_Topic.endwith(l_Suffix):
                continue;

            l_DeviceID = l_Topic[len(l_Prefix):len(l_Topic)-len(l_Suffix)];
            l_Payload  = json.loads(l_Message.payload.decode("utf-8","ignore"));

            await OnPayloadReceived(l_MqttClient, l_DeviceID, l_Payload)

# ////////////////////////////////////////////////////////////////////////////
# ////////////////////////////////////////////////////////////////////////////

# On Mqtt connect
def Mqtt_OnConnect(p_MqttClient, _, __, ___):
    l_Topic = "goveeblemqtt/zone" + str(SERVER_ZONE_ID) + "/light/+/command";

    print("Connected to Mqtt broker")
    print("Subscribing to topic: " + l_Topic);

    p_MqttClient.subscribe(l_Topic)
# On Mqtt message
def Mqtt_OnMessage(p_MqttClient, _, p_Message):
    MESSAGE_QUEUE.append(p_Message);

# ////////////////////////////////////////////////////////////////////////////
# ////////////////////////////////////////////////////////////////////////////

async def OnPayloadReceived(p_MqttClient, p_DeviceID, p_Paypload):
    l_RequestedDeviceID = p_DeviceID;
    l_Device            = None;

    try:
        p_DeviceID = ':'.join(p_DeviceID[i:i+2] for i in range(0, len(p_DeviceID), 2));

        if not p_DeviceID in DEVICES:
            DEVICES[p_DeviceID] = GoveeBleLight.Client(p_DeviceID, p_MqttClient, "goveeblemqtt/zone" + str(SERVER_ZONE_ID) + "/light/" + l_RequestedDeviceID + "/state", ADAPTER);

        l_Device        = DEVICES[p_DeviceID];
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

        print(p_DeviceID + " " + str(p_Paypload))
    except Exception as l_Exception:
        print(f"OnPayloadReceived: Something Bad happened: {l_Exception}")

# ////////////////////////////////////////////////////////////////////////////
# ////////////////////////////////////////////////////////////////////////////

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]));