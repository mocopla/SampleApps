# sample_app_moco_playground

## Table of contents

- [About](#about)
- [Getting Started](#getting_started)
- [Usage](#usage)
- [Testing](#testing)
- [Notes](#notes)

## About <a name = "about"></a>

sample_app_moco_playground is a Python script, that shows a possible implementation of an application for the MoCoPla platform. The platform is not limited to Python for application creation, but as Python is very accesible and popular, it was chosen to create this sample application. Sample apps in multiple other languages will be released in due time.  

The intended use of this specific application is, to provide a developer a guide on how to create an application. It is also intended to show the main "building blocks" that can be used to create your own application. Because of the nature of Python, being interpreted sequentially, the sample application uses multi threading. This allows for the application to receive data from the simulator and use this data "near real time"


There are two threads implemented in the script:  
1. subscriber thread - This thread handles the connection to the Moco Engine and if needed reconnection in case Moco Engine restarts. Moreover this thread handles the reception of signals from the Moco Engine and passes the signal name and value to the app thread.  The thread is implemented in a way, that it needs minimal modification by the app developer. The developer only needs to specify which signals to request from Moco Engine.  
To inform the Moco Engine which signals are required a request message, subscription list, will be sent from the app to the Moco Engine on startup. The signals requested are use the Vehicle Signal Specification (VSS) the VSS naming format. Based on signals available in te dataset a number of VSS signals is available to the developer. The request message format and an example are shown below:


```
Using VSS signals the command (CMD) key to be used is "vss":
subscription_list = {"CMD": "vss","D":"<signal_1>,<signal_2>, ... ,<signal_n>"}

Below is the message that will be used for this app, using VSS formatted signals:
subscription_list = {"CMD": "vss","D":"Vehicle.Private.PowerState,Vehicle.Powertrain.TractionBattery.StateOfCharge.Displayed,Vehicle.Powertrain.Range,Vehicle.Private.UnixTime.Seconds,Vehicle.Speed,Vehicle.Powertrain.Transmission.TravelledDistance,Vehicle.Cabin.HVAC.IsAirConditioningActive"}
```  

Besides subscribing to the signals that will be used in an application, the subscriber thread also supports functions to request the 
supported VSS vehicle signals and supported static vehicle information attributes. To request a catalogue of each of these, in the subscription list for the data section ("D") enter VSS_catalogue when requesting all supported VSS signals. The "CMD" section needs to be "vss" for this request.  
To request all supported static vehicle information attributes the "CMD" needs to be "vsi" and in the data section the request needs to have "VSI_catalogue.
Both requests will result in a list getting sent from the Moco engine to the sample app. In the sample app this list is received and printed in the console output. 

To read the data associated with with one or more static vehicle information attribute, a request using "vsi" as command and the name of the desired attribute(s) in the data field. The Moco engine will reply with the name and value of the requested signal(s).  
For example the following subscription list will request from the Moco engine the vehicle body type and powertrain type:
'''
subscription_list = {"CMD": "vsi","D":"Vehicle.Body.BodyType,Vehicle.Powertrain.Type"}
'''  
Using the vehicle profile on the playground these attributes are supported and the Moco engine will return the following values:
'''
{N: 'Vehicle.Body.BodyType', V: 'Sedan'}
{N: 'Vehicle.Powertrain.Type', V: 'EV Motor'}
''' 


2. app thread - In this thread the application will run. In this sample application a number of calculations are made using the input signals requested with the subscription list. The application takes 10 samples, every time the signal containing the time is received. After 10 samples the total time covered by the samples is calculated (the dataset available doesn't contain the time signal for every second). Over the sample time the difference between the traveled distance as read from the odometer signal (Vehicle.Powertrain.Transmission.TravelledDistance) is compared to the difference in available range between start and end of the sample time. The delta range is calculated using the signal Vehicle.Powertrain.Range;  
Based on these two values a comparison is done and the possible outcomes will be:
    1. Distance traveled is lower than the delta range value, meaning the energy used is higher than the predicted value
    2. Distance traveled matches the delta range value, meaning the energy used matched the predicted value
    3. Distance traveled is higher than the delta range value, meaning the energy used is lower than the predicted value  
The results of the calculation can be used to validate the prediction model of the range of the vehicle and if additional information is available for cases 1 and 3 (i.e. higher or lower energy consumption) the reason for this difference could be analyzed. For example if the location of the vehicle would be available in the dataset, this could be used to determine if the vehicle was traveling uphill or downhill. The state of the air conditioning can be taken into account, and in combination with ambient temperature and possibly detailed weather information the amount of power consumed by the airconditioning could be determined.  
Another calculation that is made over each sample time is the average speed during the sample time and the distance traveled based on average speed. This calculation is included to validate the accuracy of the application and the rate at which vehicle data is received. Using average speed will not be as accurate as the real odometer signal, but especially when the vehicle speed does not vary too much the value based on average speed should be close or even equal to the odometer value.

It is recomended that every application that is developed for MoCoPla follows the structure mentioned above, using two threads.

## Getting Started <a name = "getting_started"></a>

To run the application connected to the Moco platform it can be run inside a docker container, but it is also possible to execute the application directly from Python (using either IDE or command line).  

As explained in the previous section the application will use input signals (vehicle signals), that are provided by the Moco engine. Moco engine will provide the signals over a TCP connection. In this example app the TCP host and port are configured to point to a simulator that is set-up in the Moco playground. When creating a new application this configuration can be used as well, when using the same simulator. If a new simulator is created the TCP port will need to be changed to match the port shown on the playground.  

Information about starting the application using docker and Python is provided in the next section.


## Usage <a name = "usage"></a>

The latest version of the sample application can be found on Github. Please ensure to use the latest version.  

**Configuration file (cfg.ini)**
At startup, the sample application reads some configuration data from a configuration file (cfg.ini). This configuration file holds information about the connection to the simulator on the platform (host and port) as well as the path to the certificate file. In normal use the only value that should have to be adjusted is the port in the section \[tcp\]. The value must match the listening port that is shown on the simulator details on the Moco platform.  
Please keep in mind the following regarding the location of the file cfg.ini:  
1. When running the sample application inside a Docker container, please ensure the cfg.ini file is copied inside the /src folder when building the container.  
2. When running the sample application from Python IDE or command line the file needs to be inside the working directory (i.e. the directory from which the python command is invoked)  

**TLS certificate**  
The connection between moco-engine and the sample application is encrypted with TLS. To allow the connection to be established a certificate file needs to be passed to the sample application. The certificate file moco-engine.pem can be downloaded from the release on Github.  
Please keep in mind the following regarding the location of the certificate file:  
1. When running the sample application inside a Docker container, please ensure the certificate file is copied inside the /src folder when building the container.  
2. When running the sample application from Python IDE or command line the certificate file needs to be inside the working directory (i.e. the directory from which the python command is invoked)  


**To create and run the sample application Docker container:**  
  
  The repository contains two Dockerfiles that can be used, depending on the requirements for the Docker image size. When running the sample application on a PC, there migth not be a restriction on the image size. In this situation the file Dockerfile.python can be used. This Dockerfile will install Python 3.10.2 image and install the matplotlib package, that is used to create graphs of specific logged and calculated data. At the end of a simulation these graphs will get generated automatically.  
  If the Docker image is intended for deployment on in vehicle hardware where image size should be kept to a minimum the file Dockerfile.alpine should be used. This Dockerfile will install the Python 3.10.8-alpine3.16 image which will result in a much smaller image. A limitation of using the alpine image is that by default no additional Python packages can be installed. It is possible to add the support for pip, but this will increase the image size. The data that can be used to create graphs that are mentioned before will be stored in a .csv (logged_signals.csv) file when the simulation finished (i.e. when no data is received from the Moco engine for more than 45 seconds, or when Moco engine is stopped)

1. Create docker image for the sample application:

    All files required to create the docker image are contained in this repository

    Copy the certificate for TLS (ssdk-ca-combined.pem.crt) in the /src folder

    To create the docker image using the above mentioned Dockerfiles, from ~/sample_app_playground/ run the command for the respctive Dockerfile: 
    ```
    docker build . -f Dockerfile.alpine -t sample-app

    docker build . -f Dockerfile.python -t sample-app
    ```


2. Run the docker for the sample application:

    Once the docker image is created it can be started using the *docker run* command. 

    ```
    docker run --rm --name sample_app --network=host   -v <'path to local repository'>/sample_app_tesla_model3_playground/src/:/app -it sample-app  
      
    or simplified from the repository run:  
      
    docker run --rm --name sample_app --network=host -v=$(pwd)/src/:/app -it sample-app
    ```
    
    Explanation of the docker run options:  
    *--rm* : This operator will automatically remove the Docker container when it exits  
    *--name <'name'>* : This operator assigns the <'name'> to the docker to allow identification of the docker in e.g. docker process status (docker ps); Adding the name is optional and the name is free to choose.        
    *-v <"path to local_repository">/sample_app_tesla_model3_playground/src/:/app* : 
    Because the application generates a log file, a volume where the log file will be stored on the local computer needs to be mounted to the application. The command syntax is *-v <"local volume">:<"docker volume">* (where docker volume is /app as defined in the Dockerfile)

**To execute the sample application from Python:**

* The application is written in Python. Implementation and testing was done using Python 3.8.10 and further testing was done using Python 3.10.2

* To use the option of generting graphs of the logged data the library matplotlib needs to be installed using: ```pip install matplotlib```

* Application can be started either from IDE or command line. If the Moco engine is not running the application will start and wait for the Moco engine to start and display the message: "Waiting for server to (re-)start"

**Optional command line arguments when executing from Python command line**
* If the sample app is started from command line, or through a Docker file, there is an option to pass as command line arguments the host and port number for the TCP connection. The arguments are arranged as follows: sample_app.py <'host'> <'TCP port'>

To run the sample app and pass in the host and port the full command will look as follows:

```
python sample_app.py 127.0.0.1 3001
```

* If no host and port are passed as arguments the host and port configured in cfg.ini will be used by the application.


## Testing <a name = "testing"></a>
Following basic test have been carried out on the application:  
* Verify all signals transmitted from Moco engine are received inside the application, in the application thread.
* Verify CPU load and memory usage when executing application using Python resource monitor extension.  
* Verify application is able to handle disconnect and reconnect from Moco engine.  


## Notes <a name = "notes"></a>

* If the Moco engine is not running and the application is started, the application will wait for the Moco engine to start and display the message: "Waiting for server to (re-)start" with 1 second intervals.
* If there is no vehicle data being transmitted from Moco engine to the application for more than 5 seconds a synchronization message will be send from the application to Moco engine. The reason for this message is to ensure the Moco engine is still running, so the application needs to keep running. While there is no data coming from the Moco engine, every 5 seconds the following message will appear in the console output of the sample app: "Sync message from Moco engine received", provided the Moco engine is still running  
* When the application is running and receiving data from the platform simulator, various data will be logged. When the simulator is stopped the sample application will generate some graphs with the available log data. When the window showing the graphs is closed the sample application will finish and write the graph to a jpeg file.


### Who do I talk to? ###

* For clarifications and comments contact developers@mocopla.link
