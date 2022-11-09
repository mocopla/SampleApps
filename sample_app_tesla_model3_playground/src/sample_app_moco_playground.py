"""sample_app_moco_playground summary
This script is intended as an example or guide for developers to create
applications for MoCoPla. The script needs to be executed allongside the
Moco engine, which will provide input signals to this script. Intended use
is to run this script inside a docker container, but can be executed directly
from Python.
There are two threads implemented in this script. The first being the
subscriber thread and second the application thread (calculation_thread).
The subsriber thread handles the communication with the Moco Engine. It will 
connect the sample app TCP Client to the Moco engine TCP server, and will 
handle connection and if needed re-connection between client and server. 
It will also receive the data from Moco engine and pass this to the application 
thread.
The application thread is the section that the developer will implement. In
this sample there is an application that calculates the difference in remaining
range and traveled distance over time. The app will take 10 samples and calculate
the distance traveled during the sample and compare it to the difference in 
remaining range between the start and end of the sample.
Over the sample time the average vehicle speed is calculated and the using the
timestamps received from the vehicle data a traveled distance is calculated.
This calculation was used to test the accuracy of the calculations and determine
if data is received in a near real time manner. To determine this the distance
traveled calculated from average speed is compared to the value read from the 
odometer data.
"""


import errno
import logging
import os
import threading
import time
from threading import Thread, local
import queue
import socket
import ssl
import json
import csv
import sys
from configparser import ConfigParser

ALPINE_BUILD = False

try:
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
except ImportError:    
    ALPINE_BUILD = True


# Read configuration from config file
config = ConfigParser()
config.read('cfg.ini')
CERTIFICATE_PATH = config['cert']['path']
PLATFORM_HOST = config['tcp']['host']
SIMULATOR_PORT = config['tcp']['port']


# Check if command line arguments were passed to set host and port
# If no host is specified default host demo-amp.mocopla.link will be used
# If no port is specified default port 55003 will be used
if len(sys.argv) >= 2:
    TCP_HOST= sys.argv[1]
else:    
    TCP_HOST = PLATFORM_HOST
if len(sys.argv) >= 3:
    tcp_port_str = sys.argv[2]
    TCP_PORT = int(tcp_port_str)
else:
    TCP_PORT = int(SIMULATOR_PORT)


context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
context.verify_mode = ssl.CERT_OPTIONAL 
context.check_hostname = False
context.load_verify_locations(cafile = CERTIFICATE_PATH)


logging.basicConfig(
    format='%(asctime)s %(levelname)-8s: %(message)s',
    datefmt='%d-%m-%Y %H:%M:%S',
    level=logging.DEBUG,
    filename='sample_app.txt'
)
logger = logging.getLogger(__name__)

# To allert the application data is available a threading event is used
tcp_signal_update = threading.Event()
moco_engine_stopped = threading.Event()

# List of signals to request from Moco engine to be used in the application
subscription_list = {"CMD": "vss","D":"Vehicle.Private.PowerState,Vehicle.Powertrain.TractionBattery.StateOfCharge.Displayed,Vehicle.Powertrain.Range,Vehicle.Private.UnixTime.Seconds,Vehicle.Speed,Vehicle.Powertrain.Transmission.TravelledDistance,Vehicle.Cabin.HVAC.IsAirConditioningActive"}


# Define queues to communicate between threads
q_vehicle_speed = queue.Queue()
q_unix_clk_sec = queue.Queue()
q_odo = queue.Queue()
q_soc = queue.Queue()
q_range = queue.Queue()
q_power_state = queue.Queue()
q_hvac_state = queue.Queue()

# Define queues to pass logged data to main thread
q_seconds_list = queue.Queue()
q_t_axis = queue.Queue()
q_veh_spd_axis = queue.Queue()
q_soc_axis = queue.Queue()
q_hvac_state_axis = queue.Queue()
q_range_axis = queue.Queue()
q_traveled_distance_axis = queue.Queue()


def get_signals(tcp_host, tcp_port, signal_list):
    """_summary_

    Args:
        TCP_HOST : _description_ IP Address of the TCP client
        TCP_PORT : _description_ Port number of the TCP client
        signal_list :List of signals to be requested from Moco engine

    Function will set up the connection with the Moco engine. If connection 
    loss is detected the funtion will attempt to reconnect up to five times.
    When connection is established the function will receive data from Moco 
    engine. The data will be processed into signal names and values and passed 
    to the application thread using a queue. If no data is being received from 
    Moco engine a synchronisation message is periodicaly send to the Moco 
    engine to test the connection.
    """
    # Definition of synchronisation message
    sync_message = {"CMD": "sync"}

    # Flag indicating data was received from Moco Engine
    data_received = False    

    def moco_engine_connect(tcp_host, tcp_port, message_data):
        """ Funcion to connect to the TCP server in the Moco engine. The function
            can be used in case for first time connect and reconnect.
            Resulting connection will set the client port to non blocking.
            If server is not available function will wait one second before
            continuing. Once connection is established function returns True
        """
        try:
            ssl_socket.connect((tcp_host, tcp_port))
        except ConnectionError as _e:
            if _e.args[1] == 'Connection refused' or _e.args[1] == 'No connection could be made because the target machine actively refused it':
                print('Waiting for server to (re-)start')
                time.sleep(1)
            else:
                print(_e)
        else:
            ssl_socket.send(bytes(message_data, encoding="utf-8"))
            ssl_socket.setblocking(0)
            ssl_socket.settimeout(0.1)

            return True

    # Set up connection and send signal subscription to Moco engine
    # Moco engine will provide only the signals requested by the app
    # Required signals are provided in json_object
    moco_engine_connected = False
    json_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ssl_socket = context.wrap_socket(json_socket,server_hostname = tcp_host)
    json_object = signal_list
    data = json.dumps(json_object)
    while not moco_engine_connected:
        if moco_engine_connect(tcp_host, tcp_port, data):
            moco_engine_connected = True
    ssl_socket.setblocking(1)        
    moco_engine_response = ssl_socket.recv(4096)
    ssl_socket.setblocking(0)
    ssl_socket.settimeout(1)
    available_signals = moco_engine_response.decode("utf-8")
    json_parsed_response = json.loads(available_signals)
    if json_parsed_response["REP"]== "VSS_catalogue":
        print("Supported VSS signals:")                
        for signals in json_parsed_response["D"]:
            if isinstance(signals, list):
                for subsignal in signals:
                    print(subsignal)
            else:
                print(signals)
    if json_parsed_response["REP"]== "VSI_catalogue":
        print("Supported static vehicle information:")                
        for signals in json_parsed_response["D"]:
            print(signals)
    buffer = []
    buffer_update = False
    message_segment = ""

    # With connection established, receive signals and check connection
    t_start = time.time()
    while moco_engine_connected:
        try:
            received = str(ssl_socket.recv(2048), "utf-8")
        except socket.error as _e:
            if (_e.args[0] == errno.EWOULDBLOCK or _e.args[0] == "timed out" or _e.args[0] == "The read operation timed out"):
                # No message received, send sync message to Moco engine
                json_object = sync_message
                data = json.dumps(json_object)
                try:
                    ssl_socket.send(bytes(data, encoding="utf-8"))
                    msg = ssl_socket.recv(2048).decode('utf-8')
                    if msg == '{"REP":"sync"}\n':
                        print('Sync message from Moco engine received')
                        if data_received:
                            if (not 'log_end_timer' in locals()):                                                            
                                log_end_timer = time.time()
                            else:                                
                                if time.time() - log_end_timer > 30:
                                    tcp_signal_update.set()
                except socket.error as _f:
                    if (_f.args[0] == 'Broken pipe' or _f.args[0] == 'Connection reset by peer'):
                        reconnect_counter = 0
                        while reconnect_counter <=4:
                            if not moco_engine_connect(tcp_host, tcp_port, data):
                                reconnect_counter += 1
                                time.sleep(1)
                    else:
                        print(_f)
                        reconnecting = False
                        os._exit(1)
                else:
                    time.sleep(5)
            else:  # General communication error other than timeout
                if _e.args[0] == 'Transport endpoint is not connected':
                    ssl_socket.close()
                    json_socket = socket.socket(socket.AF_INET,
                                            socket.SOCK_STREAM)
                    ssl_socket = context.wrap_socket(json_socket,server_hostname = tcp_host)
                    reconnect_counter = 0
                    reconnecting = True
                    json_object = signal_list
                    data = json.dumps(json_object)
                    while (reconnecting and (reconnect_counter<=10)):
                        if not moco_engine_connect(tcp_host,tcp_port, data):
                            reconnect_counter += 1
                        else:
                            json_object = sync_message
                            data = json.dumps(json_object)
                            reconnecting = False
                    if reconnect_counter >= 5:
                        print("Re-connection to Moco engine failed")
                        moco_engine_connected = False
                        moco_engine_stopped.set()
                        tcp_signal_update.set()
                        break
        else:
            if received=='':
                # When Moco engine disconnects, socket returns empty data when
                # connection is configured as NOBLOCK. Close socket and
                # reconnect
                ssl_socket.close()
                json_socket = socket.socket(socket.AF_INET,
                                            socket.SOCK_STREAM)
                ssl_socket = context.wrap_socket(json_socket,server_hostname = tcp_host)
                reconnect_counter = 0
                reconnecting = True
                json_object = signal_list
                data = json.dumps(json_object)
                while (reconnecting and (reconnect_counter<=4)):
                    if not moco_engine_connect(tcp_host,tcp_port, data):
                        reconnect_counter += 1
                    else:
                        json_object = sync_message
                        data = json.dumps(json_object)
                        reconnecting = False
                if reconnect_counter == 5:
                    print("Re-connection to Moco engine failed")
                    # after engine stops and doesn't restart the app exits here
                    moco_engine_connected = False
                    moco_engine_stopped.set()
                    tcp_signal_update.set()
                    break
                    # os._exit(1)

            # Message received by TCP client. Signals inside message
            # are seperated by '\n' character. Message will be split
            # Signals (name and values) will be added to a buffer. In
            # case message ends "mid-signal" the last element of the
            # message is always used as the start of the next element
            # in the buffer (message_segment)
            split_message = received.split('\n')
            if len(split_message) >= 2:
                buffer.append(message_segment + split_message[0].strip())
                buffer_update = True
                for i in range(1, len(split_message) - 1):
                    buffer.append(split_message[i].strip())
                    buffer_update = True
                if ('{' in split_message[-1] and '}' in split_message[-1]):
                    buffer.append(split_message[-1].strip())
                    message_segment=""
                else:
                    message_segment = split_message[-1]
            else:
                message_segment += split_message[0]

            # Process received signals
            if buffer_update:
                for signals in buffer:
                    if signals != '':
                        json_parsed = json.loads(signals)
                    # Pass signals to application thread through queues allert
                    # application thread signals are available using thread
                    # event (tcp_signal_update)                    
                    if(buffer_update and not "REP" in json_parsed):
                        if not data_received:
                            data_received = True
                        if json_parsed["N"] == "Vehicle.Speed":
                            q_vehicle_speed.put(float(json_parsed["V"]))
                            tcp_signal_update.set()
                        if json_parsed["N"] == "Vehicle.Private.UnixTime.Seconds":
                            q_unix_clk_sec.put(float(json_parsed["V"]))
                            tcp_signal_update.set()
                        if json_parsed["N"] == "Vehicle.Powertrain.Transmission.TravelledDistance":
                            q_odo.put(float(json_parsed["V"]))
                            tcp_signal_update.set()
                        if json_parsed["N"] == "Vehicle.Powertrain.TractionBattery.StateOfCharge.Displayed":
                            q_soc.put(float(json_parsed["V"]))
                            tcp_signal_update.set()
                        if json_parsed["N"] == "Vehicle.Powertrain.Range":
                            q_range.put(float(json_parsed["V"]))
                            tcp_signal_update.set()
                        if json_parsed["N"] == "Vehicle.Private.PowerState":
                            q_power_state.put(json_parsed["V"])
                            # tcp_signal_update.set()
                        if json_parsed["N"] == "Vehicle.Cabin.HVAC.IsAirConditioningActive":
                            q_hvac_state.put(json_parsed["V"])
                            # tcp_signal_update.set()


                buffer_update = False
                buffer = []


def app_calculations():
    """_summary_
    Example application performing calculations described in summary
    his section is to be implemented by a developer and calculations
    below are intended as a sample of a possible application
    This application will receive signals from the subscriber thread. When
    new data is available the subscriber thread will raise an event
    (tcp_signal_update) to alert the app to receive new signals and perform
    calculations. Signals will be provided through a queue. By checking if
    the queue is not empty the application will know which signal is updated
    """
    
    # Local copies of queued signals coming from the subsriber thread
    lcl_vehicle_speed = 0
    lcl_unix_clk_sec = 0
    lcl_odo = 0
    lcl_soc = 0
    lcl_power_state = ""
    lcl_hvac_state = 0
    lcl_range = 0  

    # Variables used for flow control between subscribed and app thread
    time_out_start = 0
    signal_update = False

    # Local variables used in app calculation
    seconds_list = [0]
    last_power_state = ""
    delta_soc = 0    
    time_stamp = 0
    traveled_dist_odo = 0
    traveled_dist_odo_total = 0
    times_spd = 0    
    sum_spd = 0
    avg_spd = 0
    

    # Local arrays to store logging data 
    t = []
    veh_spd_array = []
    soc_array = []
    hvac_state_array = []
    range_array = []  
    distance_traveled_array = []

    while True:
        # Check if updated signals are available
        tcp_signal_update.wait()
        if not q_vehicle_speed.empty():
            lcl_vehicle_speed = q_vehicle_speed.get(-1)
            signal_update = True            
        if not q_unix_clk_sec.empty():
            lcl_unix_clk_sec = q_unix_clk_sec.get(-1)
            time_out_start = time.time()
            signal_update = True
        if q_unix_clk_sec.empty():
            time_since_last_update = time.time() - time_out_start
            # Addition for log files with only one drive cycle. When log file completes
            # after 45 seconds of not receiving data the driving cycle will finish
            if ((time_since_last_update > 45) & (last_power_state == "VEHICLE_POWER_STATE_DRIVE")) | moco_engine_stopped.is_set():
                drive_cycle = False
                # Populate queues with logged data allowing for post processing
                q_t_axis.put(t)
                q_veh_spd_axis.put(veh_spd_array)
                q_soc_axis.put(soc_array)  
                q_hvac_state_axis.put(hvac_state_array)
                q_range_axis.put(range_array)
                q_traveled_distance_axis.put(distance_traveled_array)
                # Exit this thread
                break
        if not q_soc.empty():
            lcl_soc = q_soc.get(-1)            
            signal_update = True
        if not q_odo.empty():
            lcl_odo = q_odo.get(-1)
            signal_update = True
        if not q_power_state.empty():
            lcl_power_state = q_power_state.get(-1)
            signal_update = True
        if not q_range.empty():
            lcl_range = q_range.get(-1)
            signal_update = True
        if not q_hvac_state.empty:
            lcl_hvac_state = q_hvac_state(-1)
            signal_update = True

        # If new signals were received from the subrsciber thread
        # signal_update will be True. Only run calculations when new
        # data was received
        if signal_update:
            signal_update = False
            # Data collection
            if len(seconds_list) < 11:
                head_sec = seconds_list[-1]
                
                if head_sec != lcl_unix_clk_sec:
                    seconds_list.append(lcl_unix_clk_sec)    
                    # Create an array of time stamps that can be used to plot results over time
                    if('t_previous' in locals()):
                        time_stamp += lcl_unix_clk_sec - t_previous
                        t.append(time_stamp)
                    else:
                        t.append(0)
                    t_previous = lcl_unix_clk_sec
                    veh_spd_array.append(lcl_vehicle_speed)
                    soc_array.append(lcl_soc)
                    hvac_state_array.append(lcl_hvac_state)
                    range_array.append((round(lcl_range/1000,3)))
                    if (not 'previous_odo' in locals()):
                        previous_odo = lcl_odo
                        traveled_distance = 0
                    else:
                        if previous_odo > 0:
                            traveled_distance += lcl_odo - previous_odo
                        else:
                            traveled_distance = 0
                        previous_odo = lcl_odo
                    distance_traveled_array.append(traveled_distance)
                    

                    # Speed summed up for average speed calculation
                    sum_spd = sum_spd + lcl_vehicle_speed
                    times_spd += 1                                        
            else:
                # Data collection done

                # Calculate time between last and first sample in this period
                actual_time = seconds_list[-1] - seconds_list[1]
                hours = actual_time/3600.00

                # State of charge change
                if 'lcl_soc' in locals():
                    if not 'start_soc' in locals():
                        start_soc = lcl_soc                        
                    if ('last_soc' in locals()) and ('start_soc' in locals()):
                        delta_soc = last_soc - lcl_soc
                        # Calculate the change of state of charge from start to end of log/simulation
                        if start_soc > 0:
                            delta_soc_since_start = start_soc - delta_soc
                        else:
                            delta_soc_since_start = 0
                    last_soc = lcl_soc    

                # Calculate average speed over sample period
                if times_spd>0:
                    avg_spd = sum_spd / times_spd

                # Calculate distance traveled, since start of simulation, based on average speed
                traveled_dist_calc = hours * avg_spd
                if 'traveled_dist_calc_total' in locals():
                    traveled_dist_calc_total += traveled_dist_calc
                else:
                    traveled_dist_calc_total = traveled_dist_calc
                # Calculate distance traveled since start of simulation, based on odometer signal
                if 'last_odo' in locals():
                    if last_odo > 0:
                        traveled_dist_odo = lcl_odo - last_odo
                        last_odo = lcl_odo
                    else:      
                        traveled_dist_odo = 0               
                        last_odo = lcl_odo
                else:
                    traveled_dist_odo = 0               
                    last_odo = lcl_odo
                traveled_dist_odo_total += traveled_dist_odo

                # Calculate difference in estimated range during this period
                if 'prev_range' in locals():
                    delta_range = prev_range - lcl_range
                    prev_range = lcl_range
                else:
                    delta_range = 0
                    prev_range = lcl_range

                # Compare to distance traveled
                if delta_range > traveled_dist_odo:
                    message = (f"Simulator Time: {time_stamp} : Range drop higher than prediction. Current range: {round(lcl_range/1000,3)} km")
                    logger.info(message)
                    print(message)
                else:
                    if traveled_dist_odo > delta_range:
                        message = (f"Simulator Time: {time_stamp} seconds - Range drop lower than prediction. Current range: {round(lcl_range/1000,3)} km")
                        logger.info(message)
                        print(message)
                    else:
                        message = (f"Simulator Time: {time_stamp} seconds - Range drop matched prediction. Current range: {round(lcl_range/1000,3)} km")
                        logger.info(message)
                        print(message)


                # Calculate number of drive cycles during simulation
                if (not 'drive_cycle_count' in locals()):
                    drive_cycle_count = 0
                if (lcl_power_state == "VEHICLE_POWER_STATE_DRIVE"):
                    last_power_state = lcl_power_state
                if (lcl_power_state != "VEHICLE_POWER_STATE_DRIVE") & (last_power_state == "VEHICLE_POWER_STATE_DRIVE"):
                    last_power_state = lcl_power_state                    
                    drive_cycle_count += 1

                seconds_length = len(seconds_list)-1

                message = (f"Average speed {round(avg_spd,5)} (km/h), \
calculated distance traveled {round(traveled_dist_calc_total,3)} (km), \
distance traveled odometer {round(traveled_dist_odo_total,3)} (km), State of charge \
change in sample: {delta_soc} (%), Current state of charge {lcl_soc}")

                logger.info(message)
                print(message)


                sum_spd = 0
                avg_spd = 0
                last_speed = 0
                times_spd = 0
                seconds_list.clear()
                seconds_list.append(0)

        # Reset thread event
        tcp_signal_update.clear()


def main():
    """_summary_
    Main function setting up and starting subscriber and application thread
    """
    logger.info('-------------- (Re-)started APP --------------')
    subscriber_thread = Thread(target=get_signals, args=(TCP_HOST, TCP_PORT, subscription_list))
    calculation_thread = Thread(target=app_calculations)
    subscriber_thread.start()
    calculation_thread.start()
    
    # Wait for the calculation thread to finish
    calculation_thread.join()
    
    # Now process the data received from the vehicle    
    time_axis = q_t_axis.get()
    veh_spd_axis = q_veh_spd_axis.get()
    soc_axis = q_soc_axis.get()
    hvac_state_axis = q_hvac_state_axis.get()
    range_axis = q_range_axis.get()
    distance_traveled_axis = q_traveled_distance_axis.get()

    # Create graph using the data received from the vehicle
    if not ALPINE_BUILD:
        figure, subplot = plt.subplots(2, 2)    
        subplot[1 ,0].plot(time_axis, veh_spd_axis)
        subplot[1, 0].set_title("Vehicle speed")
        subplot[0, 0].plot(time_axis, soc_axis)
        subplot[0, 0].set_title("State of charge")
        subplot[0, 1].plot(time_axis, range_axis, 'b-', label="Range")
        subplot[0, 1].set_title("Range vs Distance traveled")
        subplot2 = subplot[0, 1].twinx()
        subplot2.invert_yaxis()
        subplot2.plot(time_axis, distance_traveled_axis, 'r-', label="Distance traveled")
        subplot[1, 1].plot(time_axis, distance_traveled_axis)
        subplot[1, 1].set_title("Distance traveled")
        plt.show()
        file_name_time = str(time.time())
        filename = "graph_"+file_name_time+".jpg"
        figure.savefig(filename, format='jpeg', dpi=100)
    
    # Write logged signals to CSV file
    with open('logged_signals.csv', 'w') as output_file:        
        csv_writer = csv.writer(output_file)
        csv_writer.writerow(time_axis)
        csv_writer.writerow(veh_spd_axis)
        csv_writer.writerow(soc_axis)
        csv_writer.writerow(hvac_state_axis)
        csv_writer.writerow(range_axis)
        csv_writer.writerow(distance_traveled_axis)


if __name__ == '__main__':
    main()
