import network
import ubinascii
import ujson
import utime
from secrets import secrets
import uasyncio as a 
from async_websocket_client import AsyncWebsocketClient
import gc
from machine import Pin,SPI
from random import randint
from neopixel import NeoPixel
from w5x00 import w5x00_init

# trying to read config --------------------------------------------------------
# if config file format is wrong, exception is raised and program will stop
print("Trying to load config...")

f = open("../config.json")
text = f.read()
f.close()
config = ujson.loads(text)
del text
# ---------------------------------------------------------
NUMBER_PIXELS = 16
LED_PIN = 28
th = [100,100,100]
thx = 1
rgb = (0,100,0)
ring = NeoPixel(Pin(LED_PIN), NUMBER_PIXELS)

async def blink_ring():
    global rgb
    ndx = 0
    while True:   
        for i in range(0,16,2):
            ring[i] = rgb
        ring.write() # send the data from RAM down the wire
        await a.sleep_ms(200) # keep on 1/10 of a second

        ring.fill([0,0,0])
        ring.write() # send the data from RAM down the wire
        await a.sleep_ms(1000) # keep on 1/10 of a second
# ------------------------------------------------------------------------------
print("Create WS instance...")
# create instance of websocket
ws = AsyncWebsocketClient(config['socket_delay_ms'])
print(config["server"])
print("Created.")
# this lock will be used for data interchange between loops --------------------
# better choice is to use uasynio.queue, but it is not documented yet
lock = a.Lock()
# this array stores messages from server
data_from_ws = []
# Function for main control loop.
# It makes sense for ESP32 with integrated LED on Pin2.
# Write another function for main loop for other controller types.
p2 = Pin("LED", Pin.OUT)
async def blink_sos():
    global p2

    async def blink(on_ms: int, off_ms: int):
        p2.on()
        await a.sleep_ms(on_ms)
        p2.off()
        await a.sleep_ms(off_ms)

    await blink(200, 50)    

# ------------------------------------------------------
# Main loop function: blink and send data to server.
# This code emulates main control cycle for controller.
async def blink_loop():
    global lock
    global data_from_ws
    global ws
    global rgb
    global th
    global thx
    global btns

    # Main "work" cycle. It should be awaitable as possible.
    while True:
        await blink_sos()
        if ws is not None:
            if await ws.open():
                s1 = "SOS!"
                ln = len(btns)
                if ln>0:
                    s1 = btns[0] 
                    del(btns[0])
                await ws.send(s1)
            print("SOS!", end=' ')

            # lock data archive
            await lock.acquire()
            while True:
                ln = len(data_from_ws)
                if ln>0:
                    item = data_from_ws[0] 
                    try:                                      
                        js = ujson.loads(item)
                        print("\nData from ws: {}#{}".format(js,ln))
                        del(data_from_ws[0])
                        if js['payload']=="RED":
                            thx = 0                       
                        elif js['payload']=='BLU':
                            thx = 2                       
                        elif js['payload']=='GRE':
                            thx = 1                      
                        elif js['payload']=='Th+':
                            th[thx] = th[thx]+5 if th[thx]+5<=255 else 0                        
                        elif js['payload']=='Th-':
                            th[thx] = th[thx]-5 if th[thx]-5>=0 else 255                    
                    finally:
                        print("json except")

                    if thx==0:
                        rgb = (th[thx],0,0) 
                    elif thx==1:
                        rgb = (0,th[thx],0) 
                    else:
                        rgb = (0,0,th[thx])

                    print("RGB[{}]={}".format(thx,rgb))

                else:
                    break
            lock.release()
            gc.collect()

        await a.sleep_ms(50)

# ------------------------------------------------------------------------
button1 = Pin(17, Pin.IN)  # 14 number pin is input
button2 = Pin(27, Pin.IN)  # 14 number pin is input
btn1 = button1.value()
btn2 = button2.value()
btns = []

async def button_click():
    global btns,btn1,btn2

    while True:
        pb1_state = button1.value()
        if pb1_state != btn1 and pb1_state:     # if push_button pressed
            await lock.acquire()
            btns.append("btn1")
            lock.release()                  
        btn1 = pb1_state

        pb2_state = button2.value()
        if pb2_state != btn2 and pb2_state:     # if push_button pressed
            await lock.acquire()
            btns.append("btn2")
            lock.release()   
        btn2 = pb2_state

        await a.sleep_ms(1)
# ------------------------------------------------------------------------
# SSID - network name
# pwd - password
# attempts - how many time will we try to connect to WiFi in one cycle
# delay_in_msec - delay duration between attempts
async def wifi_connect(SSID: str='jinyistudio', pwd: str='25433692', attempts: int = 3, delay_in_msec: int = 300) -> network.WLAN:
    wifi = network.WLAN(network.STA_IF)

    wifi.active(1)
    count = 1

    while not wifi.isconnected() and count <= attempts:
        print("WiFi connecting. Attempt {}.".format(count))
        if wifi.status() != network.STAT_CONNECTING:
            wifi.connect(SSID, pwd)

        await a.sleep_ms(delay_in_msec)
        count += 1

    if wifi.isconnected():
        print("ifconfig: {}".format(wifi.ifconfig()))
    else:
        print("Wifi not connected.")

    return wifi

async def w5100s_connect()-> network.WIZNET5K:
    spi = SPI(0,2_000_000, mosi=Pin(19),miso=Pin(16),sck=Pin(18))
    nic = network.WIZNET5K(spi,Pin(17),Pin(20)) #spi,cs,reset pin
    nic.active(True)
    
    #None DHCP
    nic.ifconfig(('192.168.1.20','255.255.255.0','192.168.11.1','192.168.1.1'))
    
    #DHCP
    #nic.ifconfig('dhcp')
    print('IP address :', nic.ifconfig()) 

    while not nic.isconnected():
        await a.sleep(1)
        #print(nic.regs())

    if nic.isconnected():
        print("ifconfig: {}".format(nic.ifconfig()))
    else:
        print("WIZNET5K not connected.")
     
    
    return nic    
   
# ------------------------------------------------------
# Task for read loop
async def read_loop():
    global config
    global lock
    global data_from_ws

    # may be, it
    #wifi = await wifi_connect(config["wifi"]["SSID"], config["wifi"]["password"])
    wifi = await w5100s_connect()
    while True:
        gc.collect()
        if not wifi.isconnected():
            #wifi = await wifi_connect(config["wifi"]["SSID"], config["wifi"]["password"])
            wifi = await w5100s_connect()
            if not wifi.isconnected():
                await a.sleep_ms(config["wifi"]["delay_in_msec"])
                continue
        try:
            print("Handshaking...")
            # connect to test socket server with random client number
            if not await ws.handshake(uri=config["server"]):
                raise Exception('Handshake error.')
            print("...handshaked.")

            mes_count = 0
            while await ws.open():
                data = await ws.recv()
                #print("Data: " + str(data) + "; " + str(mes_count))
            
                # close socket for every 10 messages (even ping/pong)
                if mes_count == 30:
                    await ws.close()
                    print("ws is open: " + str(await ws.open()))
                mes_count += 1

                if data is not None:
                    await lock.acquire()
                    data_from_ws.append(data)
                    lock.release()

                await a.sleep_ms(50)
        except Exception as ex:
            print("Exception: {}".format(ex))
            await a.sleep(1)
# ------------------------------------------------------

async def main():

    tasks = [read_loop(),button_click(), blink_loop(), blink_ring()]
    await a.gather(*tasks)

a.run(main())

