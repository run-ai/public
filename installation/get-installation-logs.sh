#!/bin/bash

# Print logs of helm hooks if installation failed
hook_pods=$(kubectl get pod -n runai -l run.ai/hook 2> /dev/null | wc -l)
if [ $hook_pods -ne 0 ]
then
  kubectl logs -n runai -l run.ai/hook
fi

runaiconfig="$(kubectl get runaiconfig runai -n runai 2> /dev/null; echo $?)"
if [[ $runaiconfig -eq 0 ]]
then
  kubectl logs -n runai -l name=runai | grep ERROR
fi
