# Copyright 2020 Xilinx Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

""" Module for registering DPUv2 (now DPUCZDX8G) zcu104 target """

import os
import pyxir
import logging

from pyxir.graph.transformers import subgraph

from pyxir.contrib.target.DPUCZDX8G.zcu104 import xgraph_dpu_optimizer,\
    xgraph_dpu_quantizer, xgraph_dpu_zcu104_compiler

logger = logging.getLogger('pyxir')


def xgraph_dpuv2_zcu104_build_func(xgraph, work_dir=os.getcwd(), **kwargs):

    # TODO here or in optimizer, both?
    # DPU layers are in NHWC format because of the tensorflow
    #   intemediate structure we use to communicate with
    #   DECENT/DNNC

    return subgraph.xgraph_build_func(
        xgraph=xgraph,
        target='dpuv2-zcu104',
        xtype='DPU',
        layout='NHWC',
        work_dir=work_dir
    )

pyxir.register_target('dpuv2-zcu104',
                      xgraph_dpu_optimizer,
                      xgraph_dpu_quantizer,
                      xgraph_dpu_zcu104_compiler,
                      xgraph_dpuv2_zcu104_build_func)
