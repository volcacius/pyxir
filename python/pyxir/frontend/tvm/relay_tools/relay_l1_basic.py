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

"""
Module for transforming Relay L1 operators to XLayer objects

L1: Basic NN operators that enable fully connected multi-layer perceptron


"""

import math
import logging
import numpy as np

import tvm

from pyxir import graph
from pyxir.graph.layer import xlayer_factory as xlf

from .relay_2_xlayer_registry import register_relay_2_xlayer_converter,\
    register_relay_2_xlayer_converter_base

logger = logging.getLogger("pyxir")


@register_relay_2_xlayer_converter('add')
def add(expr, params, schedule, net, op_idx, RELAY_2_XLAYER, **kwargs):
    # type: (tvm.relay.expr.Expr, Dict[str, numpy.ndarray], List[Expr],
    #   Dict[int, XLayer], Dict[str, int], Dict[str, Function]) -> XLayer
    """
    TODO

    Relay
    -----
    Type: tvm.relay.op.tensor.add
    Ref: https://docs.tvm.ai/api/python/relay/op.html
    Parameters:
        - lhs (relay.Expr)
            The left hand side input data
        - rhs (relay.Expr)
            The right hand side input data
    """
    if expr in net:
        logger.debug("MEMORY: ADD")
        # This expressions is already transformed so we reuse that one
        return net[expr]

    lhs_expr, lhs_expr_class = expr.args[0], expr.args[0].__class__.__name__
    rhs_expr, rhs_expr_class = expr.args[1], expr.args[1].__class__.__name__

    lhs_layer = RELAY_2_XLAYER[lhs_expr_class](lhs_expr, params, schedule,
                                               net, op_idx, RELAY_2_XLAYER,
                                               **kwargs)

    # TODO Handling constants
    if lhs_expr not in net and ('Constant' not in lhs_layer.type
                                or lhs_layer.data[0].ndim > 1):
        schedule.append(lhs_expr)
        net[lhs_expr] = lhs_layer

    rhs_layer = RELAY_2_XLAYER[rhs_expr_class](rhs_expr, params, schedule,
                                               net, op_idx, RELAY_2_XLAYER,
                                               **kwargs)

    if rhs_expr not in net and ('Constant' not in rhs_layer.type
                                or rhs_layer.data[0].ndim > 1):
        schedule.append(rhs_expr)
        net[rhs_expr] = rhs_layer

    logger.debug("add: {}".format(""))
    logger.debug("-- lhs: {}, {}, {}, {}".format(
        expr.args[0].__class__.__name__, lhs_layer.type,
        lhs_layer.name, lhs_layer.shapes))
    logger.debug("-- rhs: {}, {}, {}, {}".format(
        expr.args[1].__class__.__name__, rhs_layer.type,
        rhs_layer.name, rhs_layer.shapes))

    def get_add_const_layer(in_layer, const_layer):

        # Numpy style broadcasting == NHWC
        const_ndim = const_layer.data[0].ndim
        if const_ndim == 1:
            # Create name
            op_name = 'nn_bias_add-' + str(hash(expr))

            const_size = const_layer.data[0].shape[0]
            in_shape = in_layer.shapes
            # Retrieve axis according to numpy broadcasting rules
            axis = [i for i in range(len(in_shape)-1, -1, -1)
                    if in_shape[i] == const_size][0]
            X = xlf.get_xop_factory_func('BiasAdd')(
                op_name, in_layer, const_layer, axis,
                relay_id=[hash(expr)])

            in_layer.tops.append(X.name)
        else:
            # Create name
            op_name = 'add-' + str(hash(expr))

            X = xlf.get_xop_factory_func('Add')(op_name,
                                                [in_layer, const_layer],
                                                relay_id=[hash(expr)])

            in_layer.tops.append(X.name)
            const_layer.tops.append(X.name)

        return X

    # 1. Adding two constants -> precompute
    # 2. One constant and one tensor -> NotImplementedError # TODO
    # 3. Two tensors -> Eltwise layer
    if 'Constant' in lhs_layer.type and 'Constant' in rhs_layer.type:
        # TODO: TEST
        # Don't add previous layers to schedule
        data = np.add(lhs_layer.data[0], rhs_layer.data[0])

        op_name = 'constant-' + str(hash(expr))

        X = xlf.get_xop_factory_func('Constant')(op_name, data,
                                                 relay_id=[hash(expr)])

    elif 'Constant' in lhs_layer.type and 'Constant' not in rhs_layer.type:
        X = get_add_const_layer(rhs_layer, lhs_layer)
    elif 'Constant' in rhs_layer.type and 'Constant' not in lhs_layer.type:
        X = get_add_const_layer(lhs_layer, rhs_layer)
    else:
        # Create name
        op_name = 'eltwise-' + str(hash(expr))

        # Create ParametersLayer
        X = xlf.get_xop_factory_func('Eltwise')(op_name, lhs_layer, rhs_layer,
                                                relay_id=[hash(expr)])

        # !Important: set input layer tops:
        lhs_layer.tops.append(X.name)
        rhs_layer.tops.append(X.name)

    return X


@register_relay_2_xlayer_converter('nn.batch_norm')
def nn_batch_norm(expr, params, schedule, net, op_idx, RELAY_2_XLAYER,
                  **kwargs):
    # type: (tvm.relay.expr.Expr, Dict[str, numpy.ndarray], List[Expr],
    #   Dict[int, XLayer], Dict[str, int], Dict[str, Function]) -> XLayer
    """
    TODO

    Relay
    -----
    Type: tvm.relay.op.nn.nn.batch_norm
    Ref: https://docs.tvm.ai/api/python/relay/nn.html#tvm.relay.op.nn.
         nn.batch_norm
    Parameters:
        - data (tvm.relay.Expr)
            Input to which batch_norm will be applied.
        - gamma (tvm.relay.Expr)
            The gamma scale factor.
        - beta (tvm.relay.Expr)
            The beta offset factor.
        - moving_mean (tvm.relay.Expr)
            Running mean of input,
        - moving_var (tvm.relay.Expr)
            Running variance of input.
        - axis (int, optional, default=1)
            Specify along which shape axis the channel is specified.
        - epsilon (double, optional, default=1e-5)
            Small float added to variance to avoid diving by zero.
        - center (boolean, optional, default=True)
            If True, add offset of beta to normalized tensor, If False, beta
            is ignored.
        - scale (boolean, optional, default=True)
            If true, multiply by gamma. If False, gamma is not used. When the
            next layer is piecewise linear (also e.g. nn.relu), this can be
            disabled since the scaling will be done by the next layer.
    """
    if expr in net:
        logger.debug("MEMORY: NN BATCH NORM")
        # This expressions is already transformed so we reuse that one
        return net[expr]

    axis = int(expr.attrs.axis)
    epsilon = float(expr.attrs.epsilon)
    center = bool(expr.attrs.center)
    scale = bool(expr.attrs.scale)

    data_expr, data_expr_class = \
        expr.args[0], expr.args[0].__class__.__name__
    gamma_expr, gamma_expr_class = \
        expr.args[1], expr.args[1].__class__.__name__
    beta_expr, beta_expr_class = expr.args[2], expr.args[2].__class__.__name__
    mean_expr, mean_expr_class = expr.args[3], expr.args[3].__class__.__name__
    variance_expr, variance_expr_class = \
        expr.args[4], expr.args[4].__class__.__name__

    data_layer = RELAY_2_XLAYER[data_expr_class](data_expr, params, schedule,
                                                 net, op_idx, RELAY_2_XLAYER,
                                                 **kwargs)
    gamma_layer = RELAY_2_XLAYER[gamma_expr_class](gamma_expr, params,
                                                   schedule, net, op_idx,
                                                   RELAY_2_XLAYER, **kwargs)
    beta_layer = RELAY_2_XLAYER[beta_expr_class](beta_expr, params, schedule,
                                                 net, op_idx, RELAY_2_XLAYER,
                                                 **kwargs)
    mean_layer = RELAY_2_XLAYER[mean_expr_class](mean_expr, params, schedule,
                                                 net, op_idx, RELAY_2_XLAYER,
                                                 **kwargs)
    variance_layer = RELAY_2_XLAYER[variance_expr_class](variance_expr, params,
                                                         schedule, net, op_idx,
                                                         RELAY_2_XLAYER,
                                                         **kwargs)

    logger.debug("nn_batch_norm: {}".format(""))

    # Update schedule with input data layer
    if data_expr not in net:
        schedule.append(data_expr)
        net[data_expr] = data_layer

    # Create XLayer
    if not scale:
        # set gamma to 1
        if 'gamma' not in op_idx:
            op_idx['gamma'] = 0
        gamma_name = 'gamma' + str(op_idx['gamma'])
        op_idx['gamma'] += 1

        new_gamma = np.ones(gamma_layer.data[0].shape)
        gamma_layer = \
            xlf.get_xop_factory_func('Constant', internal=True)(gamma_name,
                                                                new_gamma)
    if not center:
        # set beta to 0
        if 'beta' not in op_idx:
            op_idx['beta'] = 0
        beta_name = 'beta' + str(op_idx['beta'])
        op_idx['beta'] += 1

        new_beta = np.zeros(beta_layer.data[0].shape)
        beta_layer = \
            xlf.get_xop_factory_func('Constant', internal=True)(beta_name,
                                                                new_beta)

    # Create name
    op_name = 'nn_batch_norm-' + str(hash(expr))

    X = xlf.get_xop_factory_func('BatchNorm')(
        op_name,
        data_layer, mean_layer,
        variance_layer,
        gamma_layer, beta_layer,
        axis, epsilon,
        relay_id=[hash(expr)])
    logger.debug("-- bn outshape: {}".format(list(X.shapes)))

    # !Important: set input layer tops:
    data_layer.tops.append(op_name)

    return X


@register_relay_2_xlayer_converter('nn.bias_add')
def nn_bias_add(expr, params, schedule, net, op_idx, RELAY_2_XLAYER, **kwargs):
    # type: (tvm.relay.expr.Expr, Dict[str, numpy.ndarray], List[Expr],
    #   Dict[int, XLayer], Dict[str, int], Dict[str, Function]) -> XLayer
    """
    TODO
    """
    if expr in net:
        logger.debug("MEMORY: NN BIAS ADD")
        # This expressions is already transformed so we reuse that one
        return net[expr]

    axis = int(expr.attrs.axis)
    data_expr, data_expr_class = expr.args[0], expr.args[0].__class__.__name__
    bias_expr, bias_expr_class = expr.args[1], expr.args[1].__class__.__name__

    data_layer = RELAY_2_XLAYER[data_expr_class](data_expr, params, schedule,
                                                 net, op_idx, RELAY_2_XLAYER,
                                                 **kwargs)
    bias_layer = RELAY_2_XLAYER[bias_expr_class](bias_expr, params, schedule,
                                                 net, op_idx, RELAY_2_XLAYER,
                                                 **kwargs)

    logger.debug("nn_bias_add, axis: {}".format(axis))

    assert(bias_layer.data is not None)

    # Update schedule with child layers
    # ! We don't add bias layer as this bias is precomputed
    # TODO What if bias layer can't be precomputed
    # TODO WHat if bias layer is shared
    if data_expr not in net:
        schedule.append(data_expr)
        net[data_expr] = data_layer

    # Create ParametersLayer

    # Create name
    op_name = 'nn_bias_add-' + str(hash(expr))

    X = xlf.get_xop_factory_func('BiasAdd')(
        op_name, data_layer, bias_layer, axis,
        relay_id=[hash(expr)])
    logger.debug("--outshape: {}".format(list(X.shapes)))
    # ! The recursive parent decides whether the layer should be added to the
    #   schedule or not

    # !Important: set input layer tops:
    data_layer.tops.append(op_name)

    return X


@register_relay_2_xlayer_converter('concatenate')
def concatenate(expr, params, schedule, net, op_idx, RELAY_2_XLAYER, **kwargs):
    # type: (tvm.relay.expr.Expr, Dict[str, numpy.ndarray], List[Expr],
    #   Dict[int, XLayer], Dict[str, int], Dict[str, Function]) -> XLayer
    """
    TODO

    Relay
    -----
    Type: tvm.relay.op.tensor.concatenate
    Ref: https://docs.tvm.ai/api/python/relay/op.html
    Parameters:
        - data (Union(List[relay.Expr], Tuple[relay.Expr]))
            A list of tensors.
        - axis (int)
            The axis along which the tensors are concatenated.
    """
    if expr in net:
        return net[expr]

    axis = int(expr.attrs.axis)
    # logger.debug(expr.args[0].__class__.__name__)
    logger.debug("Concatenate")

    data_layers = []
    relay_idx = []
    if isinstance(expr.args[0], tvm.relay.expr.Tuple):
        relay_idx.append(hash(expr.args[0]))
    for data_expr in expr.args[0]:
        data_expr_class = data_expr.__class__.__name__
        logger.debug("-- {}".format(data_expr_class))
        data_layer = RELAY_2_XLAYER[data_expr_class](data_expr, params,
                                                     schedule, net, op_idx,
                                                     RELAY_2_XLAYER, **kwargs)
        data_layers.append(data_layer)

        if data_expr not in net:
            net[data_expr] = data_layer
            schedule.append(data_expr)

    data_layer_types = [dl.type[0] for dl in data_layers]
    if len(set(data_layer_types)) == 1 and 'Constant' in data_layer_types:
        # Concatenate all constants TODO
        raise NotImplementedError("")
    elif 'Constant' in data_layer_types:
        raise NotImplementedError("")

    # Create XLayer
    op_name = 'concat-' + str(hash(expr))

    relay_idx.append(hash(expr))
    X = xlf.get_xop_factory_func('Concat')(op_name, data_layers, axis,
                                           relay_id=relay_idx)
    logger.debug("-- newshape: {}".format(list(X.shapes)))

    for data_layer in data_layers:
        data_layer.tops.append(X.name)

    return X


@register_relay_2_xlayer_converter('nn.dense')
def nn_dense(expr, params, schedule, net, op_idx, RELAY_2_XLAYER, **kwargs):
    # type: (tvm.relay.expr.Expr, Dict[str, numpy.ndarray], List[Expr],
    #   Dict[int, XLayer], Dict[str, int], Dict[str, Function]) -> XLayer
    """
    TODO

    Relay
    -----
    Type: tvm.relay.op.nn.nn.dense
    Ref: https://docs.tvm.ai/api/python/relay/nn.html
    Parameters:
        - data (tvm.relay.Expr)
            The input data to the operator.
        - weight (tvm.relay.Expr)
            The weight expressions.
        - units (int, optional)
            Number of hidden units of the dense transformation.
        - out_dtype (str, optional)
            Specifies the output data type for mixed precision dense.
    """
    if expr in net:
        logger.debug("MEMORY: DENSE")
        # This expressions is already transformed so we reuse that one
        return net[expr]

    units = int(expr.attrs.units)
    data_expr, data_expr_class = expr.args[0], expr.args[0].__class__.__name__
    weights_expr, weights_expr_class = \
        expr.args[1], expr.args[1].__class__.__name__

    data_layer = RELAY_2_XLAYER[data_expr_class](data_expr, params, schedule,
                                                 net, op_idx, RELAY_2_XLAYER,
                                                 **kwargs)
    weights_layer = RELAY_2_XLAYER[weights_expr_class](weights_expr, params,
                                                       schedule, net, op_idx,
                                                       RELAY_2_XLAYER,
                                                       **kwargs)

    logger.debug("nn_dense: {}".format(""))

    assert len(data_layer.shapes) == 2
    assert weights_layer.data is not None

    # Update schedule with child layers
    # ! We don't add weights layer as this weight is precomputed
    # TODO What if weights layer can't be precomputed
    # TODO WHat if weights layer is shared
    if data_expr not in net:
        schedule.append(data_expr)
        net[data_expr] = data_layer

    # Create XLayer

    # Create name
    op_name = 'nn_dense-' + str(hash(expr))

    X = xlf.get_xop_factory_func('Dense')(op_name, data_layer,
                                          weights_layer, units,
                                          relay_id=[hash(expr)])

    # !Important: set input layer tops:
    data_layer.tops.append(op_name)

    return X


@register_relay_2_xlayer_converter('nn.dropout')
def nn_dropout(expr, params, schedule, net, op_idx, RELAY_2_XLAYER, **kwargs):
    # type: (tvm.relay.expr.Expr, Dict[str, numpy.ndarray], List[Expr],
    #   Dict[int, XLayer], Dict[str, int], Dict[str, Function]) -> XLayer
    """
    TODO

    Relay
    -----
    Type: tvm.relay.op.nn.nn.droput
    Ref: https://docs.tvm.ai/api/python/relay/nn.html
    Parameters:
        - data (tvm.relay.Expr)
            The input data to the operator.
        - rate (float, optional (default=0.5))
            The probability for an element to be reset to 0.
    """
    if expr in net:
        logger.debug("MEMORY: DROPoUT")
        # This expressions is already transformed so we reuse that one
        return net[expr]

    rate = float(expr.attrs.rate)

    data_expr, data_expr_class = expr.args[0], expr.args[0].__class__.__name__
    data_layer = RELAY_2_XLAYER[data_expr_class](data_expr, params, schedule,
                                                 net, op_idx, RELAY_2_XLAYER,
                                                 **kwargs)

    logger.debug("nn_dropout")

    # Update schedule with child layers
    if data_expr not in net:
        schedule.append(data_expr)
        net[data_expr] = data_layer

    # Create XLayer
    # Create name
    op_name = 'nn_dropout-' + str(hash(expr))

    X = xlf.get_xop_factory_func('Dropout')(op_name, data_layer, rate,
                                            relay_id=[hash(expr)])

    # !Important: set input layer tops:
    data_layer.tops.append(op_name)

    return X


@register_relay_2_xlayer_converter_base('exp')
def exp(op_name, expr, in_xlayers):
    # type: (str, tvm.relay.expr.Expr, List[XLayer]) -> XLayer
    """
    Compute elementwise exponent

    Relay
    -----
    Type: tvm.relay.exp
    Ref: https://docs.tvm.ai/langref/relay_op.html
    Parameters:
        - data (tvm.relay.Expr)
            The input data to the operator.
    """

    X = xlf.get_xop_factory_func('Exp')(op_name, in_xlayers,
                                        relay_id=hash(expr))

    return X


@register_relay_2_xlayer_converter_base('expand_dims')
def expand_dims(op_name, expr, in_xlayers):
    # type: (str, tvm.relay.expr.Expr, List[XLayer]) -> XLayer
    """
    Insert new axises at the position specified by the axis attribute

    Relay
    -----
    Type: tvm.relay.exp
    Ref: https://docs.tvm.ai/langref/relay_op.html#tvm.relay.expand_dims
    Parameters:
        - data (tvm.relay.Expr)
            The input data to the operator.
        - axis (int)
            The axis at which the input array is expanded. Should lie in range
            [-data.ndim - 1, data.ndim]. If axis < 0, it is the first axis
            inserted; If axis >= 0, it is the last axis inserted in Python's
            negative indexing.
        - num_newaxis (int)
            Number of axes to be inserted. Should be >= 0.
    """

    axis = int(expr.attrs.axis)
    num_newaxis = int(expr.attrs.num_newaxis)

    X = xlf.get_xop_factory_func('ExpandDims')(op_name, in_xlayers,
                                               axis=axis,
                                               num_newaxis=num_newaxis,
                                               relay_id=[hash(expr)])

    return X


@register_relay_2_xlayer_converter_base('log')
def log(op_name, expr, in_xlayers):
    # type: (str, tvm.relay.expr.Expr, List[XLayer]) -> XLayer
    """
    Compute elementwise logarithm

    Relay
    -----
    Type: tvm.relay.log
    Ref: https://docs.tvm.ai/langref/relay_op.html
    Parameters:
        - data (tvm.relay.Expr)
            The input data to the operator.
    """

    X = xlf.get_xop_factory_func('Log')(op_name, in_xlayers,
                                        relay_id=[hash(expr)])

    return X


@register_relay_2_xlayer_converter('multiply')
def multiply(expr, params, schedule, net, op_idx, RELAY_2_XLAYER, **kwargs):
    # type: (tvm.relay.expr.Expr, Dict[str, numpy.ndarray], List[Expr],
    #   Dict[int, XLayer], Dict[str, int], Dict[str, Function]) -> XLayer
    """
    TODO

    Relay
    -----
    Type: tvm.relay.op.tensor.multiply
    Ref: https://docs.tvm.ai/api/python/relay/op.html
    Parameters:
        - lhs (relay.Expr)
            The left hand side input data
        - rhs (relay.Expr)
            The right hand side input data
    """
    if expr in net:
        logger.debug("MEMORY: MULTIPLY")
        # This expressions is already transformed so we reuse that one
        return net[expr]

    lhs_expr, lhs_expr_class = expr.args[0], expr.args[0].__class__.__name__
    rhs_expr, rhs_expr_class = expr.args[1], expr.args[1].__class__.__name__

    lhs_layer = RELAY_2_XLAYER[lhs_expr_class](lhs_expr, params, schedule, net,
                                               op_idx, RELAY_2_XLAYER,
                                               **kwargs)
    rhs_layer = RELAY_2_XLAYER[rhs_expr_class](rhs_expr, params, schedule, net,
                                               op_idx, RELAY_2_XLAYER,
                                               **kwargs)

    logger.debug("multiply: {}".format(""))
    logger.debug("-- lhs: {}".format(expr.args[0].__class__.__name__))
    logger.debug("-- rhs: {}".format(expr.args[1].__class__.__name__))

    def add_scale_layer(inpt_layer, scale_layer):
        # TODO
        # Create XLayer

        # Create ParametersLayer

        # Create name
        op_name = 'scale-' + str(hash(expr))

        # Create beta name
        beta_name = 'beta-' + str(hash(expr))

        beta = scale_layer.data[0] * 0  # numpy.ndarray
        beta_layer = \
            xlf.get_xop_factory_func('Constant', internal=True)(beta_name,
                                                                beta)

        X = xlf.get_xop_factory_func('Scale')(op_name, inpt_layer,
                                              scale_layer, beta_layer,
                                              axis=-1,
                                              relay_id=[hash(expr)])

        return X

    # 1. Multiplying two constants -> precompute
    # 2. One constant and one tensor -> Scale layer
    # 3. Two tensors -> NotImplementedError
    if 'Constant' in lhs_layer.type and 'Constant' in rhs_layer.type:
        # TODO: TEST
        # Don't add previous layers to schedule
        data = np.multiply(lhs_layer.data, rhs_layer.data)

        op_name = 'constant-' + str(hash(expr))

        X = xlf.get_xop_factory_func('Constant')(op_name, data,
                                                 relay_id=[hash(expr)])

    elif 'Constant' in lhs_layer.type and 'Constant' not in rhs_layer.type:
        X = add_scale_layer(rhs_layer, lhs_layer)

        # Update schedule with child layers
        # ! We don't add scale layer as this scale is added to the input layer
        if rhs_expr not in net:
            schedule.append(rhs_expr)
            net[rhs_expr] = rhs_layer

        # !Important: set input layer tops:
        rhs_layer.tops.append(X.name)

    elif 'Constant' in rhs_layer.type and 'Constant' not in lhs_layer.type:
        X = add_scale_layer(lhs_layer, rhs_layer)

        # Update schedule with child layers
        # ! We don't add scale layer as this scale is added to the input layer
        if lhs_expr not in net:
            schedule.append(lhs_expr)
            net[lhs_expr] = lhs_layer

        # !Important: set input layer tops:
        lhs_layer.tops.append(X.name)
    else:

        op_name = 'multiply-' + str(hash(expr))

        X = xlf.get_xop_factory_func('Multiply')(op_name,
                                                 [lhs_layer, rhs_layer],
                                                 relay_id=[hash(expr)])

        if lhs_expr not in net:
            schedule.append(lhs_expr)
            net[lhs_expr] = lhs_layer

        # !Important: set input layer tops:
        lhs_layer.tops.append(X.name)

        if rhs_expr not in net:
            schedule.append(rhs_expr)
            net[rhs_expr] = rhs_layer

        # !Important: set input layer tops:
        rhs_layer.tops.append(X.name)

    return X


@register_relay_2_xlayer_converter('nn.relu')
def nn_relu(expr, params, schedule, net, op_idx, RELAY_2_XLAYER, **kwargs):
    # type: (tvm.relay.expr.Expr, Dict[str, numpy.ndarray], List[Expr],
    #   Dict[int, XLayer], Dict[str, int], Dict[str, Function]) -> XLayer
    """
    TODO

    Relay
    -----
    Type: tvm.relay.op.nn.nn.relu
    Ref: https://docs.tvm.ai/api/python/relay/nn.html
    Parameters:
        - data (tvm.relay.Expr)
            The input data
    """
    if expr in net:
        logger.debug("MEMORY: RELU")
        # This expressions is already transformed so we reuse that one
        return net[expr]

    data_expr, data_expr_class = expr.args[0], expr.args[0].__class__.__name__

    data_layer = RELAY_2_XLAYER[data_expr_class](data_expr, params, schedule,
                                                 net, op_idx, RELAY_2_XLAYER,
                                                 **kwargs)

    logger.debug("nn_relu: {}".format(""))

    # Update schedule with input data layer
    if data_expr not in net:
        schedule.append(data_expr)
        net[data_expr] = data_layer

    # Create ParametersLayer

    # Create name
    op_name = 'nn_relu-' + str(hash(expr))

    X = xlf.get_xop_factory_func('ReLU')(op_name, data_layer,
                                         relay_id=[hash(expr)])
    logger.debug("-- outshape: {}".format(list(X.shapes)))

    # !Important: set input layer tops:
    data_layer.tops.append(op_name)

    return X


@register_relay_2_xlayer_converter_base('rsqrt')
def rsqrt(op_name, expr, in_xlayers):
    # type: (str, tvm.relay.expr.Expr, List[XLayer]) -> XLayer
    """
    Compute elementwise rsqrt

    Relay
    -----
    Type: tvm.relay.log
    Ref: https://docs.tvm.ai/langref/relay_op.html
    Parameters:
        - data (tvm.relay.Expr)
            The input data to the operator.
    """

    X = xlf.get_xop_factory_func('rSqrt')(op_name, in_xlayers,
                                          relay_id=[hash(expr)])

    return X


@register_relay_2_xlayer_converter_base('sigmoid')
def sigmoid(op_name, expr, in_xlayers):
    # type: (str, tvm.relay.expr.Expr, List[XLayer]) -> XLayer
    """
    Compute elementwise sigmoid

    Relay
    -----
    Type: tvm.relay.sigmoid
    Ref: https://docs.tvm.ai/langref/relay_op.html
    Parameters:
        - data (tvm.relay.Expr)
            The input data to the operator.
    """

    X = xlf.get_xop_factory_func('Sigmoid')(op_name, in_xlayers,
                                            relay_id=[hash(expr)])

    return X


@register_relay_2_xlayer_converter_base('nn.softmax')
def nn_softmax(op_name, expr, in_xlayers):
    # type: (str, tvm.relay.expr.Expr, List[XLayer]) -> XLayer
    """
    TODO

    Relay
    -----
    Type: tvm.relay.op.nn.nn.softmax
    Ref: https://docs.tvm.ai/api/python/relay/nn.html
    Parameters:
        - data (tvm.relay.Expr)
            The input data
        - axis (int, optional)
            The axis to sum over when computing softmax
    """

    axis = int(expr.attrs.axis)

    X = xlf.get_xop_factory_func('Softmax')(op_name, in_xlayers,
                                            axis=axis,
                                            relay_id=[hash(expr)])
    logger.debug("-- outshape: {}".format(list(X.shapes)))

    return X


@register_relay_2_xlayer_converter_base('sqrt')
def sqrt(op_name, expr, in_xlayers):
    # type: (str, tvm.relay.expr.Expr, List[XLayer]) -> XLayer
    """
    Compute elementwise sqrt

    Relay
    -----
    Type: tvm.relay.log
    Ref: https://docs.tvm.ai/langref/relay_op.html
    Parameters:
        - data (tvm.relay.Expr)
            The input data to the operator.
    """

    X = xlf.get_xop_factory_func('Sqrt')(op_name, in_xlayers,
                                         relay_id=[hash(expr)])

    return X
