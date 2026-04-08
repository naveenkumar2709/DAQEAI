@echo off
SETLOCAL ENABLEEXTENSIONS ENABLEDELAYEDEXPANSION

set datfpath=D:/My_Workspace/testing_data/datf_main/QE_ATF
set container=daqe_ai
set image=daqe_spark_new

docker ps -a --filter "name=%container%" --format "{{.Names}}" > temp_exists.txt
set /p CONTAINER_EXISTS=<temp_exists.txt
del temp_exists.txt

if "%CONTAINER_EXISTS%"=="" (
    echo Container does not exist. Creating a new container...
    docker run -dt -p 8505:8505 -v %datfpath%:/app -w /app --name %container% %image% bash
) else (
    echo Container exists, Stopping/Starting/Running the container...
    docker stop %container%
    timeout /t 3 /nobreak >nul
    docker start %container%
    timeout /t 2 /nobreak >nul
)
echo Installing Plugins...
docker exec -u root %container% bash -c "python3 -m pip install --upgrade pip"
docker exec -u root %container% bash -c "sh datf_core/scripts/install.sh"
docker exec -u root %container% bash -c "export PYTHONPATH=%datfpath%"
echo Starting Website...
docker exec -u root %container% bash -c "sh datf_core/scripts/websitestart.sh"
