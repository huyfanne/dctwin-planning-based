### Local Setup
Step 1. Install python dependencies via pip (with Anaconda)
```bash
# under the repo root
$ conda create -n dcwiz-ai-engine python=3.9
$ conda activate dcwiz-ai-engine
$ pip install -r requirements.txt
```

Step 1.5. Note that you will need to install `dctwin` separately as it's in a private repository
```bash
# under the repo root
$ mkdir 3rdparty && git clone git@github.com:CAP-GDCR/dctwin-exp.git ./3rdparty/dctwin
$ pip install 3rdparty/dctwin/dctwin-0.3.0-py3-none-any.whl
```

Step 2. Install **EnergyPlus == 9.5.0** from [here](https://github.com/NREL/EnergyPlus/releases/tag/v9.5.0).
```bash
# under any desired directory <dir>
$ wget https://github.com/NREL/EnergyPlus/releases/download/v9.5.0/EnergyPlus-9.5.0-de239b2e5f-Linux-Ubuntu18.04-x86_64.sh
$ bash EnergyPlus-9.5.0-de239b2e5f-Linux-Ubuntu18.04-x86_64.sh
```
Note that the default EnergyPlus install location is `/usr/local/EnergyPlus-9-5-0`. 
If you do not have access to it, just specify an alternative path during installation.

Step 3. Install **BCVTB** from [here](https://simulationresearch.lbl.gov/bcvtb/Download#Release_1.6.0_.28April_21.2C_2016.29)
```bash
# under any desired directory <dir>
$ wget http://github.com/lbl-srg/bcvtb/releases/download/v1.6.0/bcvtb-install-linux64-v1.6.0.jar
$ java -jar bcvtb-install-linux64-v1.6.0.jar
```
Note that the default BCVTB install location is `bcvtb` under your current dir.

Step 4. Try the demo experiment under `examples/`

4.1. Change the following field of `engine.prototxt`
```
...
eplus_env_config {
  eplus_runnable: "<your_eplus_installation_path>/energyplus"  # e.g. /usr/local/EnergyPlus-9-5-0/energyplus
  bcvtb_home: "<your_bcvtb_folder>" # e.g. /usr/local/bcvtb
  ...
}
...
```

4.2. Depending on your environment, you may need to add the following to your `PYTHONPATH`
```
export PYTHONPATH=$PYTHONPATH:<your_path>/dcwiz-ai-engine
```

4.3. Run the script
```bash
# under examples/main.py
$ python main.py
```

### Config with Protobuf
If you updated any '.proto'

1. Download ProtoBuf Compiler [here](https://github.com/protocolbuffers/protobuf/releases/tag/v3.19.4), 
   base on your computer OS (e.g. For Windows developers, you should download `protoc-x.x.x-win64.zip`
2. After extracting it, you will find a runnable named `protoc` (could be a binary or .exe, should be under `bin/`)
3. Recompile the `.proto` that you changed:
```
$ protoc -I=<your_project_dir>/dcwiz-ai-engine/engine/envs/ds/protos --python_out=<your_project_dir>/dcwiz-ai-engine/engine/envs/ds <your_project_dir>/dcwiz-ai-engine/engine/envs/ds/protos/<name>.proto
```
Check [this](https://developers.google.com/protocol-buffers/docs/pythontutorial) out if you are confused

