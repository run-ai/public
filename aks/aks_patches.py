import os
import sys
import json
import subprocess

# kubectl patch RunaiConfig runai -n runai -p '{"spec": {"global": {"gpuOperator": {"namespace": "temp-namespace"}}}}' --type="merge"

DEBUG = True
GPU_TOLERATION = {'effect': 'NoSchedule', 'key': 'nvidia.com/gpu', 'operator': 'Exists'}
GPU_SKU_TOLERATION = {'effect': 'NoSchedule', 'key': 'sku', 'operator': 'Equal', 'value': 'gpu'}

DCGM_EXPORTER_NAMESPACE = 'gpu-resources'
DCGM_EXPORTER_VALUES_YAML = """
image:
  repository: nvcr.io/nvidia/k8s/dcgm-exporter
  pullPolicy: IfNotPresent
  tag: 2.3.5-2.6.5-ubuntu20.04

arguments: []

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
- effect: NoSchedule
  key: sku
  operator: Equal
  value: gpu
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
    def __init__(self):
        PatchingDs.__init__(self, 'gpu-feature-discovery')
        ds_name = self._get_gfd_ds_name()
        self._get_json_command = 'kubectl get ds {} -n node-feature-discovery -ojson'.format(ds_name)

    def _get_gfd_ds_name(self):
        return 'gpu-feature-discovery'

    def edit_ds_json(self, ds_json):
        add_gpu_toleration_if_needed(ds_json)
        add_gpu_sku_toleration_if_needed(ds_json)


class Nfd(PatchingDs):
    def __init__(self):
        PatchingDs.__init__(self, 'node-feature-discovery')
        self._get_json_command = 'kubectl get ds nfd-worker -n node-feature-discovery -ojson'

    def edit_ds_json(self, ds_json):
        add_gpu_toleration_if_needed(ds_json)
        add_gpu_sku_toleration_if_needed(ds_json)


class DcgmExporter(PatchingDs):
    def __init__(self):
        PatchingDs.__init__(self, 'dcgm-exporter')
        self._get_json_command = 'kubectl get ds dcgm-exporter -n {} -ojson'.format(DCGM_EXPORTER_NAMESPACE)

    def _pre_patch(self):
        debug_print('Installing dcgm-exporter (if needed)')

        dcgm_exporter_values_filepath = 'dcgm-exporter-values-temp.yaml'
        write_to_file(DCGM_EXPORTER_VALUES_YAML, dcgm_exporter_values_filepath)

        install_dcgm_exporter_commands = [
            'helm repo add gpu-helm-charts https://nvidia.github.io/gpu-monitoring-tools/helm-charts',
            'helm repo update',
            'helm install -f {} dcgm-exporter gpu-helm-charts/dcgm-exporter -n {}'.format(dcgm_exporter_values_filepath, DCGM_EXPORTER_NAMESPACE)
        ]

        for command in install_dcgm_exporter_commands:
            exec_command(command)

        os.remove(dcgm_exporter_values_filepath)

    def edit_ds_json(self, ds_json):
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
def add_toleration(ds_json, toleration):
    debug_print('Adding toleration to ds')

    tolerations = ds_json['spec']['template']['spec'].get('tolerations')
    if not tolerations:
        ds_json['spec']['template']['spec']['tolerations'] = []

    ds_json['spec']['template']['spec']['tolerations'].append(toleration)

def add_toleration_if_needed(ds_json, toleration):
    is_toleration_found = False
    tolerations = ds_json['spec']['template']['spec'].get('tolerations')
    if tolerations:
        for toleration in tolerations:
            if toleration == toleration:
                is_toleration_found = True
                break

    if is_toleration_found:
        debug_print('Toleration already found in ds')
        return

    add_toleration(ds_json, toleration)

def add_gpu_toleration_if_needed(ds_json):
    debug_print('Adding GPU toleration if needed')
    return add_toleration_if_needed(ds_json, GPU_TOLERATION)

def add_gpu_sku_toleration_if_needed(ds_json):
    debug_print('Adding GPU sku toleration if needed')
    return add_toleration_if_needed(ds_json, GPU_SKU_TOLERATION)

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
def patch_runaiconfig():
    debug_print('Patching runaiconfig with dcgm-exporter namespace')
    patch_command = 'kubectl patch RunaiConfig runai -n runai -p \'{"spec": {"global": {"nvidiaDcgmExporter": {"namespace": "%s", "installedFromGpuOperator": false}}}}\' --type="merge"' % (DCGM_EXPORTER_NAMESPACE, )
    exec_string_command(patch_command)

################ main ################
def patch_for_gke():
    ds_to_patch = [Gfd()], Nfd(), DcgmExporter()]
    for ds in ds_to_patch:
        ds.patch()

    patch_runaiconfig()

def main():
    patch_for_gke()

if __name__ == "__main__":
    main()