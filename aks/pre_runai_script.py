import sys
import subprocess


def exec_command(command):
    output = subprocess.run(command.split(), stdout=subprocess.PIPE)
    return str(output.stdout, 'utf-8') if output is not None else ""

def create_monitoring_ns():
    print("Creating namespace monitoring")
    create_monitoring_ns_command = 'kubectl create namespace monitoring'
    exec_command(create_monitoring_ns_command)

def install_gfd_if_needed(version):
    if version < 2.5:
        print("No need to install gfd for version: {}".format(version))
        return

    install_gfd_commands = [
        'helm repo add nvgfd https://nvidia.github.io/gpu-feature-discovery',
        'helm repo update',
        'helm install --version=0.5.0 gpu-feature-discovery nvgfd/gpu-feature-discovery'
    ]

    for command in install_gfd_commands:
        exec_command(command)

def parse_args():
    if len(sys.argv) < 2:
        exit('Please provide the runai-version as an argument for the script, for example:\n'+
        '"python3 pre_runai_script.py 2.4"')

    version_arg = sys.argv[1]
    try:
        version = float(version_arg)
    except ValueError:
        version = 0

    if version < 2.4:
        exit('Valid versions are: 2.4, 2.5..., for example:\n"python3 gke_patches.py 2.4 <DCGM_NAMESPACE>"')

    return version

def main():
    version = parse_args()

    # TODO: MAYBE: install_aks_nvidia_device_plugin()
    create_monitoring_ns()
    install_gfd_if_needed(version)

if __name__ == "__main__":
    main()