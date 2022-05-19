import os
import sys
import json
import subprocess


DEBUG = True
GPU_TOLERATION = {'effect': 'NoSchedule', 'key': 'nvidia.com/gpu', 'operator': 'Exists'}


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

def exec_string_command(string_command):
    output = subprocess.run(string_command, stdout=subprocess.PIPE, shell=True)
    return str(output.stdout, 'utf-8') if output is not None else ""

def apply_json(json_content):
    json_filepath = '/tmp/json_to_deploy.json'
    write_to_file(json.dumps(json_content), json_filepath)

    apply_json_command = 'kubectl apply -f {}'.format(json_filepath)
    exec_command(apply_json_command)

    os.remove(json_filepath)

def add_nvidia_volumes(ds_json):
    debug_print('Adding nvidia volume to ds')

    volumes = ds_json['spec']['template']['spec'].get('volumes')
    if not volumes:
        ds_json['spec']['template']['spec']['volumes'] = []

    volumeMounts = ds_json['spec']['template']['spec']['containers'][0].get('volumeMounts')
    if not volumeMounts:
        ds_json['spec']['template']['spec']['containers'][0]['volumeMounts'] = []

    nvidia_volume = {'hostPath': {'path': '/home/kubernetes/bin/nvidia', 'type': 'Directory'}, 'name': 'nvidia-volume'}
    nvidia_volume_mount = {'mountPath': '/usr/local/nvidia', 'name': 'nvidia-volume'}

    ds_json['spec']['template']['spec']['volumes'].append(nvidia_volume)
    ds_json['spec']['template']['spec']['containers'][0]['volumeMounts'].append(nvidia_volume_mount)

def add_nvidia_volumes_if_needed(ds_json):
    is_nvidia_volume_found = False
    volumes = ds_json['spec']['template']['spec'].get('volumes')
    if volumes:
        for volume in volumes:
            if volume['hostPath']['path'] == '/home/kubernetes/bin/nvidia':
                is_nvidia_volume_found = True
                break

    if is_nvidia_volume_found:
        debug_print('Nvidia volume already found in ds')
        return

    add_nvidia_volumes(ds_json)

################ gpu-feature-discovery ################
def remove_priority_class(gfd_json):
    priorityClass = gfd_json['spec']['template']['spec'].get('priorityClassName')
    if not priorityClass:
        return

    debug_print('Removing priorityClassName from gpu-feature-discovery')
    gfd_json['spec']['template']['spec']['priorityClassName'] = None

def get_gfd_ds_name(version):
    if version == '2.4':
        return 'runai-cluster-gpu-feature-discovery'
    if version == '2.5':
        return 'gpu-feature-discovery'
    return ''

def get_gfd_json(version):
    debug_print('Getting gpu-feature-discovery json')
    ds_name = get_gfd_ds_name(version)
    get_gfd_json_command = 'kubectl get ds {} -n node-feature-discovery -ojson'.format(ds_name)
    json_output = exec_command(get_gfd_json_command)
    return json.loads(json_output)

def edit_gfd_json(gfd_json):
    add_nvidia_volumes_if_needed(gfd_json)
    remove_priority_class(gfd_json)

def edit_gfd(version):
    gfd_json = get_gfd_json(version)
    edit_gfd_json(gfd_json)
    debug_print('Applying edited gpu-feature-discovery')
    apply_json(gfd_json)

################ node-feature-discovery ################
def add_gpu_toleration(ds_json):
    debug_print('Adding gpu toleration to ds')

    tolerations = ds_json['spec']['template']['spec'].get('tolerations')
    if not tolerations:
        ds_json['spec']['template']['spec']['tolerations'] = []

    ds_json['spec']['template']['spec']['tolerations'].append(GPU_TOLERATION)

def add_gpu_toleration_if_needed(ds_json):
    is_gpu_toleration_found = False
    tolerations = ds_json['spec']['template']['spec'].get('tolerations')
    if tolerations:
        for toleration in tolerations:
            if GPU_TOLERATION == toleration:
                is_gpu_toleration_found = True
                break

    if is_gpu_toleration_found:
        debug_print('GPU toleration already found in ds')
        return

    add_gpu_toleration(ds_json)

def get_nfd_json():
    debug_print('Getting node-feature-discovery json')
    get_nfd_json_command = 'kubectl get ds nfd-worker -n node-feature-discovery -ojson'
    json_output = exec_command(get_nfd_json_command)
    return json.loads(json_output)

def edit_nfd_json(nfd_json):
    add_gpu_toleration_if_needed(nfd_json)

def edit_nfd(version):
    if version != '2.5':
        debug_print('No need to edit nfd - version: {}'.format(version))

    nfd_json = get_nfd_json()
    edit_nfd_json(nfd_json)
    debug_print('Applying edited node-feature-discovery')
    apply_json(nfd_json)

################ dcgm-exporter ################

def get_dcgm_exporter_json(dcgm_exporter_namespace):
    debug_print('Getting dcgm-exporter json')
    get_dcgm_exporter_json_command = 'kubectl get ds dcgm-exporter -n {} -ojson'.format(dcgm_exporter_namespace)
    json_output = exec_command(get_dcgm_exporter_json_command)
    return json.loads(json_output)

def edit_dcgm_exporter_json(dcgm_exporter_json):
    add_nvidia_volumes_if_needed(dcgm_exporter_json)

def edit_dcgm_exporter(dcgm_exporter_namespace):
    dcgm_exporter_json = get_dcgm_exporter_json(dcgm_exporter_namespace)
    edit_dcgm_exporter_json(dcgm_exporter_json)
    debug_print('Applying edited dcgm-exporter')
    apply_json(dcgm_exporter_json)

################ runaiconfig ################
def patch_runaiconfig(dcgm_exporter_namespace):
    debug_print('Patching runaiconfig with dcgm-exporter namespace')
    patch_command = 'kubectl patch RunaiConfig runai -n runai -p \'{"spec": {"global": {"nvidiaDcgmExporter": {"namespace": "%s", "installedFromGpuOperator": false}}}}\' --type="merge"' % (dcgm_exporter_namespace, )
    exec_string_command(patch_command)

def parse_args():
    if len(sys.argv) < 3:
        exit('Please provide the runai-version and dcgm-exporter namespace as arguments for the script, for example:\n'+
        '"python3 gke_patches.py 2.4 <DCGM_NAMESPACE>"')

    version = sys.argv[1]
    if version not in ['2.4', '2.5']:
        exit('Valid versions are: 2.4 or 2.5. For example:\n"python3 gke_patches.py 2.4 <DCGM_NAMESPACE>"')

    dcgm_exporter_namespace = sys.argv[2]
    return version, dcgm_exporter_namespace

def main():
    version, dcgm_exporter_namespace = parse_args()

    edit_gfd(version)
    edit_nfd(version)
    edit_dcgm_exporter(dcgm_exporter_namespace)
    patch_runaiconfig(dcgm_exporter_namespace)

if __name__ == "__main__":
    main()