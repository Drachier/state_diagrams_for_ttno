"""
This module provides commonly used operators as numpy arrays.
"""
from __future__ import annotations
from typing import Union, List, Tuple

import numpy as np

from ..util import crandn

def pauli_matrices(asarray: bool=True) -> Union[Tuple[List,List,List],Tuple[np.ndarray,np.ndarray,np.ndarray]]:
    """
    Returns the three Pauli matrices X, Y, and Z in Z-basis as ndarray, if asarray is True
    otherwise it returns them as lists.
    """
    X = [[0,1],
         [1,0]]
    Y = [[0,-1j],
         [1j,0]]
    Z = [[1,0],
         [0,-1]]
    if asarray:
        X = np.asarray(X, dtype="complex")
        Y = np.asarray(Y, dtype="complex")
        Z = np.asarray(Z, dtype="complex")

    return (X, Y, Z)

def bosonic_operators(dimension: int = 2) -> Tuple[np.ndarray,np.ndarray,np.ndarray]:
    """
    Supplies the common bosonic operators.

    Args:
        dimension (int, optional): The dimension of the bosonics space to be considers.
        This determines the size of all the operators. Defaults to 2.

    Returns:
        Tuple[np.ndarray,np.ndarray,np.ndarray]:
            * creation_op: Bosonic creation operator.
            * annihilation_op: Bosonic anihilation operator.
            * number_op: The bosonic number operator, i.e. a diagonal matrix with increasing
              integers on the diagonal from 0 to dimension-1.
    """
    if dimension < 1:
        errstr = "The dimension must be positive!"
        raise ValueError(errstr)
    sqrt_number_vec = np.asarray([np.sqrt(i)
                                  for i in range(1, dimension)])

    creation_op = np.diag(sqrt_number_vec, k=-1)
    annihilation_op = creation_op.T
    number_op = creation_op @ annihilation_op
    return (creation_op, annihilation_op, number_op)

def random_hermitian_matrix(size: int = 2) -> np.ndarray:
    """
    Creates a random hermitian matrix H^\dagger = H

    Args:
        size (int, optional): Size of the matrix. Defaults to 2.

    Returns:
        np.ndarray: The hermitian matrix.
    """
    if size < 1:
        errstr = "The dimension must be positive!"
        raise ValueError(errstr)
    matrix = crandn((size,size))
    return 0.5 * (matrix + matrix.T.conj()) 
