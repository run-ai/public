import os
import sys
import json
import subprocess


DEBUG = True
GPU_TOLERATION = {'effect': 'NoSchedule', 'key': 'nvidia.com/gpu', 'operator': 'Exists'}

DCGM_EXPORTER_VALUES_YAML = """
image:
  repository: nvcr.io/nvidia/k8s/dcgm-exporter
  pullPolicy: IfNotPresent
  tag: 2.3.5-2.6.5-ubuntu20.04

arguments: ["--kubernetes-gpu-id-type", "device-name"]

securityContext:
  runAsNonRoot: false
  runAsUser: 0
  capabilities:
     add: ["SYS_ADMIN"]
  privileged: true

serviceMonitor:
  enabled: false
  interval: 15s
  additionalLabels: {}

nodeSelector:
  feature.node.kubernetes.io/pci-10de.present: "true"

tolerations:
- effect: NoSchedule
  key: nvidia.com/gpu
  operator: Exists
"""


class PatchingDs():
    def __init__(self, ds_name):
        self._name = ds_name
        self._should_edit = True

    def _get_json(self):
        debug_print('Getting {} json'.format(self._name))
        json_output = exec_command(self._get_json_command)
        return json.loads(json_output)

    def _pre_patch(self):
        return

    def patch(self):
        if not self._should_edit:
            return

        self._pre_patch()

        ds_json = self._get_json()
        self.edit_ds_json(ds_json)
        debug_print('Applying edited {}'.format(self._name))
        apply_json(ds_json)

    def edit_ds_json(self, ds_json):
        raise NotImplementedError()


class Gfd(PatchingDs):
    def __init__(self, version):
        PatchingDs.__init__(self, 'gpu-feature-discovery')
        ds_name = self._get_gfd_ds_name(version)
        self._get_json_command = 'kubectl get ds {} -n node-feature-discovery -ojson'.format(ds_name)

    def _get_gfd_ds_name(self, version):
        if version == 2.4:
            return 'runai-cluster-gpu-feature-discovery'
        if version >= 2.5:
            return 'gpu-feature-discovery'
        return ''

    def edit_ds_json(self, ds_json):
        add_nvidia_volumes_if_needed(ds_json)
        remove_priority_class(ds_json)


class Nfd(PatchingDs):
    def __init__(self, version):
        PatchingDs.__init__(self, 'node-feature-discovery')

        if version < 2.5:
            debug_print('No need to edit nfd - version: {}'.format(version))
            self._should_edit = False
            return

        self._get_json_command = 'kubectl get ds nfd-worker -n node-feature-discovery -ojson'

    def edit_ds_json(self, ds_json):
        add_gpu_toleration_if_needed(ds_json)


class DcgmExporter(PatchingDs):
    def __init__(self, dcgm_exporter_namespace):
        PatchingDs.__init__(self, 'dcgm-exporter')
        self._dcgm_exporter_namespace = dcgm_exporter_namespace
        self._get_json_command = 'kubectl get ds dcgm-exporter -n {} -ojson'.format(self._dcgm_exporter_namespace)

    def _pre_patch(self):
        debug_print('Installing dcgm-exporter (if needed)')

        dcgm_exporter_values_filepath = 'dcgm-exporter-values-temp.yaml'
        write_to_file(DCGM_EXPORTER_VALUES_YAML, dcgm_exporter_values_filepath)

        install_dcgm_exporter_commands = [
            'helm repo add gpu-helm-charts https://nvidia.github.io/gpu-monitoring-tools/helm-charts',
            'helm repo update',
            'helm install -f {} dcgm-exporter gpu-helm-charts/dcgm-exporter -n {}'.format(dcgm_exporter_values_filepath, self._dcgm_exporter_namespace)
        ]

        for command in install_dcgm_exporter_commands:
            exec_command(command)

        os.remove(dcgm_exporter_values_filepath)

    def edit_ds_json(self, ds_json):
        add_nvidia_volumes_if_needed(ds_json)
        edit_probes(ds_json)


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

################ DS editing ################
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

def remove_priority_class(ds_json):
    priorityClass = ds_json['spec']['template']['spec'].get('priorityClassName')
    if not priorityClass:
        debug_print('priorityClassName not found in ds - nothing to remove')
        return

    debug_print('Removing priorityClassName from ds')
    ds_json['spec']['template']['spec']['priorityClassName'] = None

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

def edit_probe(ds_json, probe_name):
    debug_print('Editing {} for ds'.format(probe_name))
    probe = ds_json['spec']['template']['spec']['containers'][0].get(probe_name)
    if not probe:
        ds_json['spec']['template']['spec']['containers'][0][probe_name] = {}

    ds_json['spec']['template']['spec']['containers'][0][probe_name]['failureThreshold'] = 20
    ds_json['spec']['template']['spec']['containers'][0][probe_name]['initialDelaySeconds'] = 120
    ds_json['spec']['template']['spec']['containers'][0][probe_name]['periodSeconds'] = 30

def edit_probes(ds_json):
    edit_probe(ds_json, 'livenessProbe')
    edit_probe(ds_json, 'readinessProbe')

################ runaiconfig ################
def patch_runaiconfig(dcgm_exporter_namespace):
    debug_print('Patching runaiconfig with dcgm-exporter namespace')
    patch_command = 'kubectl patch RunaiConfig runai -n runai -p \'{"spec": {"global": {"nvidiaDcgmExporter": {"namespace": "%s", "installedFromGpuOperator": false}}}}\' --type="merge"' % (dcgm_exporter_namespace, )
    exec_string_command(patch_command)

################ main ################
def parse_args():
    if len(sys.argv) < 3:
        exit('Please provide the runai-version and dcgm-exporter namespace as arguments for the script, for example:\n'+
        '"python3 gke_patches.py 2.4 <DCGM_NAMESPACE>"')

    version_arg = sys.argv[1]
    try:
        version = float(version_arg)
    except ValueError:
        version = 0

    if version < 2.4:
        exit('Valid versions are: 2.4, 2.5..., for example:\n"python3 gke_patches.py 2.4 <DCGM_NAMESPACE>"')

    dcgm_exporter_namespace = sys.argv[2]
    return version, dcgm_exporter_namespace

def patch_for_gke(version, dcgm_exporter_namespace):
    ds_to_patch = [Gfd(version), Nfd(version), DcgmExporter(dcgm_exporter_namespace)]
    for ds in ds_to_patch:
        ds.patch()

    patch_runaiconfig(dcgm_exporter_namespace)

def main():
    version, dcgm_exporter_namespace = parse_args()
    patch_for_gke(version, dcgm_exporter_namespace)

if __name__ == "__main__":
    main()