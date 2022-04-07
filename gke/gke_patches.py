import os
import subprocess


DCGM_EXPORTER_NAMESPACE = 'runai'
DEBUG = True

NVIDIA_VOLUME = '''
      - hostPath:
          path: /home/kubernetes/bin/nvidia
          type: Directory
        name: nvidia
'''
NVIDIA_VOLUME_MOUNT = '''
        - mountPath: /usr/local/nvidia
          name: nvidia
'''


################ General Functions ################
def debug_print(str_to_print):
    if DEBUG:
        print(str_to_print)

def write_to_file(file_content, file_path):
    with open(file_path, 'w') as f:
        f.write(file_content)

def exec_command(command):
    output = subprocess.run(command.split(), stdout=subprocess.PIPE)
    return str(output.stdout, 'utf-8') if output is not None else ""

def apply_yaml(yaml_content):
    yaml_filepath = '/tmp/yaml_to_deploy.yaml'
    write_to_file(yaml_content, yaml_filepath)

    apply_yaml_command = 'kubectl apply -f {}'.format(yaml_filepath)
    exec_command(apply_yaml_command)

    os.remove(yaml_filepath)

def add_nvidia_volumes(gfd_yaml_line):
    if 'volumeMounts:' in gfd_yaml_line:
        debug_print('Adding nvidia volume mount')
        return gfd_yaml_line + NVIDIA_VOLUME_MOUNT
    elif 'volumes:' in gfd_yaml_line:
        debug_print('Adding nvidia volume')
        return gfd_yaml_line + NVIDIA_VOLUME
    return gfd_yaml_line

################ gpu-feature-discovery ################
def remove_priority_class(gfd_yaml_line):
    if 'priorityClassName' in gfd_yaml_line:
        debug_print('Removing priorityClassName from gpu-feature-discovery')
        return ''
    return gfd_yaml_line

def get_gfd_yaml():
    debug_print('Getting gpu-feature-discovery yaml')
    get_gfd_yaml_command = 'kubectl get ds runai-cluster-gpu-feature-discovery -n node-feature-discovery -oyaml'
    return exec_command(get_gfd_yaml_command)

def edit_gfd_yaml(gfd_yaml):
    edited_gfd = ''
    for line in gfd_yaml.splitlines():
        edited_line = remove_priority_class(line)
        edited_line = add_nvidia_volumes(edited_line)
        edited_gfd += edited_line + '\n'

    return edited_gfd

def edit_gfd():
    gfd_yaml = get_gfd_yaml()
    gfd_yaml = edit_gfd_yaml(gfd_yaml)
    debug_print('Applying edited gpu-feature-discovery')
    apply_yaml(gfd_yaml)

################ dcgm-exporter ################
def get_dcgm_exporter_namespace_from_args():
    return sys.argv[1] if len(sys.argv) > 1 else DCGM_EXPORTER_NAMESPACE

def get_dcgm_exporter_yaml():
    debug_print('Getting dcgm-exporter yaml')
    get_dcgm_exporter_yaml_command = 'kubectl get ds dcgm-exporter -n {} -oyaml'.format(get_dcgm_exporter_namespace_from_args())
    return exec_command(get_dcgm_exporter_yaml_command)

def edit_dcgm_exporter_yaml(dcgm_exporter_yaml):
    edited_dcgm_exporter = ''
    for line in dcgm_exporter_yaml.splitlines():
        edited_line = add_nvidia_volumes(edited_line)
        edited_dcgm_exporter += edited_line + '\n'

    return edited_dcgm_exporter

def edit_dcgm_exporter():
    dcgm_exporter_yaml = get_dcgm_exporter_yaml()
    dcgm_exporter_yaml = edit_dcgm_exporter_yaml(dcgm_exporter_yaml)
    debug_print('Applying edited dcgm-exporter')
    apply_yaml(dcgm_exporter_yaml)

def main():
    edit_gfd()
    edit_dcgm_exporter()

if __name__ == "__main__":
    main()