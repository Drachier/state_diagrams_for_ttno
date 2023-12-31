from __future__ import annotations
from typing import Tuple, Callable
from copy import copy, deepcopy
from collections import UserDict

import numpy as np

from .tree_structure import TreeStructure
from .node import Node
from .tensor_util import (tensor_qr_decomposition,
                          contr_truncated_svd_splitting,
                          SplitMode)
from .leg_specification import LegSpecification
from .canonical_form import (canonical_form,
                             split_qr_contract_r_to_neighbour)
from .tree_contraction import (completely_contract_tree,
                               contract_two_ttn)
from .ttn_exceptions import NotCompatibleException


class TensorDict(UserDict):
    def __init__(self, nodes, inpt=None):
        if inpt is None:
            inpt = {}
        super().__init__(inpt)
        self.nodes = nodes

    def __getitem__(self, node_id: str):
        """
        Since during addition of nodes the tensors are not actually transposed,
        this has to be done when accesing them. 
        This way whenever a tensor is accessed, its leg ordering is
            (parent_leg, children_legs, open_legs)
        """
        permutation = self.nodes[node_id].leg_permutation
        tensor = super().__getitem__(node_id)
        transposed_tensor = np.transpose(tensor, permutation)
        self.nodes[node_id]._reset_permutation()
        super().__setitem__(node_id, transposed_tensor)
        return transposed_tensor


class TreeTensorNetwork(TreeStructure):
    """
    A tree tensor network (TTN) a tree, where each node contains a tensor,
    that is part of the network. Here a tree tensor network is a dictionary
    _nodes of tensor nodes with their identifiers as keys.

    General structure and parts of the codes are from treelib.tree

    Attributes
    -------
    _nodes: dict[str, Node] mapping node ids (str) to Node objects
    _tensors: dict[str, ndarray] mapping node ids (str) to numpy ndarray objects
    _root_id: str identifier for root node of TTN
    """

    def __init__(self):
        """
        Initiates a new TreeTensorNetwork or a deep or shallow copy of a
        different one.
        """
        super().__init__()
        self._tensors = TensorDict(self._nodes)
        self.orthogonality_center_id = None

    @property
    def tensors(self):
        """
        A dict[str, np.ndarray] mapping the tensor tree node identifiers to
        the corresponding tensor data.

        Since during addition of nodes the tensors are not actually transposed,
        this has to be done here. This way whenever tensors are accessed, their
        leg ordering is
            (parent_leg, children_legs, open_legs)
        """
        return self._tensors

    @property
    def root(self) -> Tuple[Node, np.ndarray]:
        """
        Returns the root node and the associated tensor

        Returns:
            Tuple[Node, np.ndarray]: _description_
        """
        if self.root_id is None:
            errstr = "There is no root!"
            raise KeyError(errstr)
        return self[self.root_id]

    def _transpose_tensor(self, node_id: str):
        """
        Since during addition of nodes the tensors are not actually transposed,
        this has to be done when accesing them. 
        This way whenever a tensor is accessed, its leg ordering is
            (parent_leg, children_legs, open_legs)
        """
        node = self.nodes[node_id]
        tensor = self._tensors[node_id]
        transposed_tensor = np.transpose(tensor, node.leg_permutation)
        self._tensors[node_id] = transposed_tensor
        node.reset_permutation()

    def __getitem__(self, key: str) -> Tuple[Node, np.ndarray]:
        node = super().__getitem__(key)
        tensor = self._tensors[key]
        return (node, tensor)

    def __eq__(self, other: TreeTensorNetwork) -> bool:
        """
        Two TTN are considered equal, if all their nodes are equal and then the tensors
         corresponding to these nodes are equal.
        """
        if not len(self.nodes) == len(other.nodes):
            # Avoid the case that one is the subtree of the other.
            return False
        for node_id, node in self.nodes.items():
            if node_id in other.nodes: # Avoid KeyError
                nodes_equal = node == other.nodes[node_id]
                tensors_equal = np.allclose(self.tensors[node_id], other.tensors[node_id])
                if not (nodes_equal and tensors_equal):
                    return False
            else:
                return False # Some node_id is not the same
        return True

    def add_root(self, node: Node, tensor: np.ndarray):
        """
        Adds a root tensor node to the TreeTensorNetwork
        """
        node.link_tensor(tensor)
        super().add_root(node)

        self.tensors[node.identifier] = tensor

    def add_child_to_parent(self, child: Node, tensor: np.ndarray,
                            child_leg: int, parent_id: str, parent_leg: int):
        """
        Adds a Node to the TreeTensorNetwork which is the child of the Node
        with identifier `parent_id`. The two tensors are contracted along one
        leg; the child via child_leg and the parent via parent_leg
        """
        self.ensure_existence(parent_id)
        parent_node = self._nodes[parent_id]
        if tensor.shape[child_leg] != parent_node.shape[parent_leg]:
            errstr = f"Dimensionality of leg {child_leg} of {child.identifier} and of leg {parent_leg} of {parent_id} are not the same!"
            raise NotCompatibleException(errstr)
        child.link_tensor(tensor)
        self._add_node(child)
        child.open_leg_to_parent(parent_id, child_leg)

        child_id = child.identifier
        parent_node.open_leg_to_child(child_id, parent_leg)

        self.tensors[child_id] = tensor

    def add_parent_to_root(self, root_leg: int, parent: Node, tensor: np.ndarray,
                           parent_leg: int):
        """
        Adds the Node `parent` as parent to the TreeTensorNetwork's root node. The two
        nodes are connected: the root via root_leg and the parent via parent_leg.
        The root is updated to be the parent.
        """
        self._add_node(parent)
        parent.open_leg_to_child(self.root_id, parent_leg)
        new_root_id = parent.identifier
        former_root_node = self.nodes[self.root_id]
        former_root_node.open_leg_to_parent(new_root_id, root_leg)
        self._root_id = new_root_id
        self.tensors[new_root_id] = tensor

    def conjugate(self):
        """
        Returns a new TTN that is a conjugated version of the current TTN

        Returns
        -------
        ttn_conj:
            A conjugated copy of the current TTN.

        """
        ttn_conj = deepcopy(self)
        for node_id, tensor in ttn_conj.tensors.items():
            ttn_conj.tensors[node_id] = tensor.conj()
        return ttn_conj

    def absorb_tensor(self, node_id: str, absorbed_tensor: np.ndarray,
                      absorbed_tensors_leg_index: int,
                      this_tensors_leg_index: int):
        """
        Absorbs `absorbed_tensor` into this instance's tensor by contracting
        the absorbed_tensors_leg of the absorbed_tensor and the leg
        this_tensors_leg of this instance's tensor'

        Parameters
        ----------
        absorbed_tensor: np.ndarray
            Tensor to be absorbed.
        absorbed_tensors_leg_index: int
            Leg that is to be contracted with this instance's tensor.
        this_tensors_leg_index:
            The leg of this instance's tensor that is to be contracted with
            the absorbed tensor.
        """
        node_tensor = self.tensors[node_id]
        new_tensor = np.tensordot(node_tensor, absorbed_tensor,
                                  axes=(this_tensors_leg_index, absorbed_tensors_leg_index))

        this_tensors_indices = tuple(range(new_tensor.ndim))
        transpose_perm = (this_tensors_indices[0:this_tensors_leg_index]
                          + (this_tensors_indices[-1], )
                          + this_tensors_indices[this_tensors_leg_index:-1])
        self.tensors[node_id] = new_tensor.transpose(transpose_perm)

    def absorb_tensor_into_neighbour_leg(self, node_id: str, neighbour_id: str,
                                         tensor: np.ndarray, tensor_leg: int):
        """
        Absorb a tensor into a node, by contracting one of the tensor's legs with one of the
        neighbour_legs of the node.

        Args:
            node_id (str): The identifier of the node into which the tensor is absorbed
            neighbour_id (str): The identifier of the neighbour to which the leg points, which
                                 is to be contracted with the tensor
            tensor (np.ndarray): The tensor to be contracted
            tensor_leg (int): The leg of the external tensor which is to be contracted
        """
        assert tensor.ndim == 2
        node = self.nodes[node_id]
        neighbour_leg = node.get_neighbour_leg(neighbour_id)
        self.absorb_tensor(node_id, tensor, tensor_leg, neighbour_leg)

    def absorb_into_open_legs(self, node_id: str, tensor: np.ndarray):
        """
        Absorb a tensor into the open legs of the tensor of a node.
        This tensor will be absorbed into all open legs and it is assumed, the
         leg order of the tensor to be absorbed is the same as the order of
         the open legs of the node.
        The tensor to be absorbed has to have twice as many open legs as the node tensor.
         The first half of the legs is contracted with the tensor node's open legs and
         the second half become the new open legs of the tensor node.

        Args:
            node_id (str): The identifier of the node which is to be contracted with the tensor
            tensor (np.ndarray): The tensor to be contracted.
        """
        node, node_tensor = self[node_id]
        assert tensor.ndim == 2 * node.nopen_legs()

        tensor_legs = list(range(node.nopen_legs()))
        new_tensor = np.tensordot(node_tensor, tensor, axes=(node.open_legs, tensor_legs))
        # The leg ordering was not changed here
        self.tensors[node_id] = new_tensor

    def contract_nodes(self, node_id1: str, node_id2: str, new_identifier: str = ""):
        """
        Contracts two node and inserts a new node with the contracted tensor
        into the ttn.
        Note that one of the nodes will be the parent of the other.
        The resulting leg order is the following:
            `(parent_parent_leg, node1_children_legs, node2_children_legs,
            node1_open_legs, node2_open_legs)`
        The resulting node will have the identifier `parent_id + "contr" + child_id`.

        Deletes the original nodes and tensors from the TTN.

        Args:
            node_id1 (str): Identifier of first tensor
            node_id2 (str): Identifier of second tensor
            new_identifier (str): A potential new identifier. Otherwise defaults to
                `node_id1 + "contr" + node_id2`
        """
        if new_identifier == "":
            new_identifier = node_id1 + "contr" + node_id2
        parent_id, child_id = self.determine_parentage(node_id1, node_id2)
        child_node = self.nodes[child_id]
        parent_node = self.nodes[parent_id]

        # Contracting tensors
        parent_tensor = self.tensors[parent_id]
        child_tensor = self.tensors[child_id]
        new_tensor = np.tensordot(parent_tensor, child_tensor,
                                  axes=(parent_node.get_child_leg(child_id), 0))

        # remove old tensors
        self.tensors.pop(node_id1)
        self.tensors.pop(node_id2)

        # add new tensor
        self.tensors[new_identifier] = new_tensor
        new_node = Node(tensor=new_tensor, identifier=new_identifier)

        # Actual tensor leg now have the form
        # (parent_of_parent, remaining_children_of_parent, open_of_parent,
        # children_of_child, open_of_child)
        if not parent_node.is_root():
            new_node.open_leg_to_parent(parent_node.parent, 0)
        parent_children = copy(parent_node.children)
        parent_children.remove(child_id)
        parent_child_dict = {identifier: leg_value + parent_node.nparents()
                             for leg_value, identifier in enumerate(parent_children)}
        child_children_dict = {identifier: leg_value + parent_node.nlegs() - 1
                               for leg_value, identifier in enumerate(child_node.children)}
        if parent_id == node_id1:
            parent_child_dict.update(child_children_dict)
            new_node.open_legs_to_children(parent_child_dict)
        else:
            child_children_dict.update(parent_child_dict)
            new_node.open_legs_to_children(child_children_dict)
        if node_id1 != parent_id:
            new_nvirt = new_node.nvirt_legs()
            range_parent = range(new_nvirt, new_nvirt + parent_node.nopen_legs())
            range_child = range(new_nvirt + parent_node.nopen_legs(), new_node.nlegs())
            new_node.exchange_open_leg_ranges(range_parent, range_child)

        # Change connectivity
        self.replace_node_in_neighbours(new_identifier, parent_id)
        self.replace_node_in_neighbours(new_identifier, child_id)
        self._nodes[new_identifier] = new_node

    def legs_before_combination(self, node1_id: str, node2_id: str) -> Tuple[LegSpecification, LegSpecification]:
        """
        When combining two nodes, the information about their legs is lost.
         However, sometimes one wants to split the two nodes again, as they were
         before. This function provides the required leg specification for the
         splitting.

        Args:
            node1_id (str): Identifier of the first node to be combined
            node2_id (str): Identifier of the second node to be combined

        Returns:
            Tuple[LegSpecification, LegSpecification]: The leg specifications containing the
             information to split the two nodes again, to have the same legs as before
             (assuming the open legs are not transposed). Since it is not needed the 
             LegSpecification of the parent node has the identifier of the child node
             not included. Same for the LegSpecification of the child node and the
             parent legs. The open legs are the index values that the legs would have
             after contracting the two nodes.
        """

        node1 = self.nodes[node1_id]
        node2 = self.nodes[node2_id]
        tot_nvirt_legs = node1.nvirt_legs() + node2.nvirt_legs() - 2
        tot_nlegs = node1.nlegs() + node2.nlegs() - 2
        open_legs1 = list(range(tot_nvirt_legs, tot_nvirt_legs + node1.nopen_legs()))
        open_legs2 = list(range(tot_nvirt_legs + node1.nopen_legs(), tot_nlegs))
        spec1 = LegSpecification(parent_leg=None,
                                 child_legs=copy(node1.children),
                                 open_legs=open_legs1,
                                 node=None)
        spec2 = LegSpecification(parent_leg=None,
                                 child_legs=copy(node2.children),
                                 open_legs=open_legs2,
                                 node=None)
        temp = [(spec1, node1), (spec2, node2)]
        if node2.is_parent_of(node1_id):
            temp.reverse()
        temp[0][0].parent_leg = temp[0][1].parent
        temp[0][0].child_legs.remove(temp[1][1].identifier)
        if node1.is_root():
            spec1.is_root = True
        elif node2.is_root():
            spec2.is_root = True
        return (spec1, spec2)

    def _split_nodes(self, node_id: str,
                     out_legs: LegSpecification, in_legs: LegSpecification,
                     splitting_function: Callable,
                     out_identifier: str = "", in_identifier: str = "",
                     **kwargs):
        """
        Splits an node into two nodes using a specified function

        Args:
            node_id (str): The identifier of the node to be split.
            out_legs (LegSpecification): The legs associated to the output of the
             matricised node tensor. (The Q legs for QR and U legs for SVD)
            in_legs (LegSpecification): The legs associated to the input of the
             matricised node tensor: (The R legs for QR and the SVh legs for SVD)
            splitting_function (Callable): The function to be used for the splitting
            out_identifier (str, optional): An identifier for the tensor with the
            output legs. Defaults to "".
            in_identifier (str, optional): An identifier for the tensor with the input
                legs. Defaults to "".
            **kwargs: Are passed to the splitting function.
        """
        node, tensor = self[node_id]
        if out_legs.node is None:
            out_legs.node = node
        if in_legs.node is None:
            in_legs.node = node
        # Find new identifiers
        if out_identifier == "":
            out_identifier = "out_of_" + node_id
        if in_identifier == "":
            in_identifier = "in_of_" + node_id

        # Getting the numerical value of the legs
        out_legs_int = out_legs.find_leg_values()
        in_legs_int = in_legs.find_leg_values()
        out_tensor, in_tensor = splitting_function(tensor, out_legs_int, in_legs_int,
                                                   **kwargs)
        self._tensors[out_identifier] = out_tensor
        self._tensors[in_identifier] = in_tensor

        # New Nodes
        out_node = Node(tensor=out_tensor, identifier=out_identifier)
        in_node = Node(tensor=in_tensor, identifier=in_identifier)
        self._nodes[out_identifier] = out_node
        self._nodes[in_identifier] = in_node

        # Currently the tensors out and in have the leg ordering
        # (new_leg(for in), parent_leg, children_legs, open_legs, new_leg(for out))
        in_setoff = 1
        in_children = {}
        out_setoff = 0
        out_children = {}
        if in_legs.is_root:
            # In this case we have for the leg ordering for in
            # (new_leg, children_legs, open_legs)
            in_parent_leg_value = None
            in_parent_id = None
            in_children[out_identifier] = 0
            # In this case we have for the leg ordering for out
            # (children_legs, open_legs, new_leg=parent_leg)
            out_parent_leg_value = out_node.nlegs() - 1
            out_parent_id = in_identifier
            out_setoff = 1
            # Setting new root
            self._root_id = in_identifier
        elif in_legs.parent_leg is not None:
            # In this case we have for the leg ordering for in
            # (new_leg, parent_leg, children_legs, open_legs)
            in_setoff = 2
            in_parent_leg_value = 1
            in_parent_id = in_legs.parent_leg
            in_children[out_identifier] = 1
            # In this case we have for the leg ordering for out
            # (children_legs, open_legs, new_leg=parent_leg)
            out_setoff = 1
            out_parent_leg_value = out_node.nlegs() - 1
            out_parent_id = in_identifier
        elif out_legs.is_root or out_legs.parent_leg is None:
            # In this case we have for the leg ordering for in
            # (new_leg=parent_leg, children_legs, open_legs)
            in_parent_leg_value = 0
            in_parent_id = out_identifier
            # In this case we have for the leg ordering for out
            # (children_legs, open_legs, new_leg)
            out_parent_leg_value = None
            out_parent_id = None
            out_children[in_identifier] = out_node.nlegs() - 1
            # Setting new root
            self._root_id = out_identifier
        else:
            # In this case we have for the leg ordering for in
            # (new_leg=parent_leg, children_legs, open_legs)
            in_parent_leg_value = 0
            in_parent_id = out_identifier
            # In this case we have for the leg ordering for out
            # (parent_legs, children_legs, open_legs, new_leg)
            out_setoff = 1
            out_parent_leg_value = 0
            out_parent_id = out_legs.parent_leg
            out_children[in_identifier] = out_node.nlegs() - 1

        in_children.update({child_id: leg_value + in_setoff
                            for leg_value, child_id in enumerate(in_legs.child_legs)})
        out_children.update({child_id: leg_value + out_setoff
                            for leg_value, child_id in enumerate(out_legs.child_legs)})
        if in_parent_leg_value is not None and in_parent_id is not None:
            in_node.open_leg_to_parent(in_parent_id, in_parent_leg_value)
        in_node.open_legs_to_children(in_children)
        if out_parent_leg_value is not None and out_parent_id is not None:
            out_node.open_leg_to_parent(out_parent_id, out_parent_leg_value)
        out_node.open_legs_to_children(out_children)
        self.replace_node_in_some_neighbours(out_identifier, node_id,
                                             out_legs.find_all_neighbour_ids())
        self.replace_node_in_some_neighbours(in_identifier, node_id,
                                             in_legs.find_all_neighbour_ids())

        if node_id not in [out_identifier, in_identifier]:
            self._tensors.pop(node_id)
            self._nodes.pop(node_id)

    def split_node_qr(self, node_id: str,
                      q_legs: LegSpecification, r_legs: LegSpecification,
                      q_identifier: str = "", r_identifier: str = "",
                      mode: SplitMode = SplitMode.REDUCED):
        """
        Splits a node into two nodes via QR-decomposition.

        Args:
            node_id (str): Identifier of the node to be split
            q_legs (LegSpecification): The legs which should be part of the Q-tensor
            r_legs (LegSpecification): The legs which should be part of the R-tensor
            q_identifier (str, optional): An identifier for the Q-tensor.
             Defaults to "".
            r_identifier (str, optional): An identifier for the R-tensor.
             Defaults to "".
            mode: The mode to be used for the QR decomposition. For details refer to
            `tensor_util.tensor_qr_decomposition`.
        """
        self._split_nodes(node_id, q_legs, r_legs, tensor_qr_decomposition,
                          out_identifier=q_identifier, in_identifier=r_identifier,
                          mode=mode)

    def split_node_svd(self, node_id: str,
                       u_legs: LegSpecification, v_legs: LegSpecification,
                       u_identifier: str = "", v_identifier: str = "",
                       **truncation_param):
        """
        Splits a node in two using singular value decomposition. In the process the tensors
         are truncated as specified by truncation parameters. The singular values
         are absorbed into the v_legs.

        Args:
            node_id (str): Identifier of the nodes to be split
            u_legs (LegSpecification): The legs which should be part of the U tensor
            v_legs (LegSpecification): The legs which should be part of the V tensor
            u_identifier (str, optional): An identifier for the U-tensor.
             Defaults to ""
            v_identifier (str, optional): An identifier for the V-tensor.
             Defaults to "".
        """
        self._split_nodes(node_id, u_legs, v_legs, contr_truncated_svd_splitting,
                          out_identifier=u_identifier, in_identifier=v_identifier,
                          **truncation_param)

    def move_orthogonalization_center(self, new_center_id: str,
                                      mode: SplitMode = SplitMode.REDUCED):
        """
        Moves the orthogonalization center from the current node to a
         different node.

        Args:
            new_center (str): The identifier of the new
             orthogonalisation center.
            mode: The mode to be used for the QR decomposition. For details refer to
            `tensor_util.tensor_qr_decomposition`.
        """
        if self.orthogonality_center_id is None:
            errstr = "The TTN is not in canonical form, so the orth. center cannot be moved!"
            raise AssertionError(errstr)
        if self.orthogonality_center_id == new_center_id:
            # In this case we are done already.
            return
        orth_path = self.path_from_to(self.orthogonality_center_id,
                                      new_center_id)
        for node_id in orth_path[1:]:
            self._move_orth_center_to_neighbour(node_id, mode=mode)

    def _move_orth_center_to_neighbour(self, new_center_id: str,
                                       mode: SplitMode = SplitMode.REDUCED):
        """
        Moves the orthogonality center to a neighbour of the current
         orthogonality center.

        Args:
            new_center_id (str): The identifier of a neighbour of the current
             orthogonality center.
            mode: The mode to be used for the QR decomposition. For details refer to
            `tensor_util.tensor_qr_decomposition`.
        """
        assert self.orthogonality_center_id is not None
        split_qr_contract_r_to_neighbour(self,
                                         self.orthogonality_center_id,
                                         new_center_id,
                                         mode=mode)
        self.orthogonality_center_id = new_center_id

    # Functions below this are just wrappers of external functions that are
    # linked tightly to the TTN and its structure. This allows these functions
    # to be overwritten for subclasses of the TTN with more known structure.
    # The additional structure allows for more efficent algorithms than the
    # general case.

    def canonical_form(self, orthogonality_center_id: str,
                       mode: SplitMode = SplitMode.REDUCED):
        """
        Brings the TTN in canonical form with respect to a given orthogonality
         center.

        Args:
            orthogonality_center_id (str): The new orthogonality center of
             the TTN
            mode: The mode to be used for the QR decomposition. For details refer to
            `tensor_util.tensor_qr_decomposition`.
        """
        canonical_form(self, orthogonality_center_id, mode=mode)

    def orthogonalize(self, orthogonality_center_id: str,
                      mode: SplitMode = SplitMode.REDUCED):
        """
        Wrapper of canonical form.

        Args:
            orthogonality_center_id (str): The new orthogonality center of the
             TTN.
            mode: The mode to be used for the QR decomposition. For details refer to
            `tensor_util.tensor_qr_decomposition`.
        """
        self.canonical_form(orthogonality_center_id, mode=mode)

    def completely_contract_tree(self, to_copy: bool = False):
        """
        Completely contracts the given tree_tensor_network by combining all
        nodes.
        (WARNING: Can get very costly very fast. Only use for debugging.)

        Parameters
        ----------
        to_copy: bool
            Wether or not the contraction should be perfomed on a deep copy.
            Default is False.

        Returns
        -------
        In case copy is True a deep copy of the completely contracted TTN is
        returned.

        """
        return completely_contract_tree(self, to_copy=to_copy)

    def contract_two_ttn(self, other):
        """
        Contracts two TTN with the same structure. Assumes both TTN use the same
        identifiers for the nodes.

        Parameters
        ----------
        other : TreeTensorNetwork

        Returns
        -------
        result_tensor: np.ndarray
            The contraction result.

        """
        return contract_two_ttn(self, other)
