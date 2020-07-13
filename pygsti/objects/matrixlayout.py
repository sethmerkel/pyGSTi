"""
Defines the MatrixCOPALayout class.
"""
#***************************************************************************************************
# Copyright 2015, 2019 National Technology & Engineering Solutions of Sandia, LLC (NTESS).
# Under the terms of Contract DE-NA0003525 with NTESS, the U.S. Government retains certain rights
# in this software.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
# in compliance with the License.  You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0 or in the LICENSE file in the root pyGSTi directory.
#***************************************************************************************************

from ..tools import slicetools as _slct
from ..tools import listtools as _lt
from .circuitlist import CircuitList as _CircuitList
from .distlayout import _DistributableAtom
from .distlayout import DistributableCOPALayout as _DistributableCOPALayout
from .evaltree import EvalTree as _EvalTree

import numpy as _np
import collections as _collections


class _MatrixCOPALayoutAtom(_DistributableAtom):
    """
    Object that acts as "atomic unit" of instructions-for-applying a COPA strategy.
    """

    def __init__(self, unique_complete_circuits, unique_nospam_circuits, circuits_by_unique_nospam_circuits,
                 ds_circuits, group, model_shlp, dataset, offset, elindex_outcome_tuples):

        expanded_nospam_circuit_outcomes = _collections.OrderedDict()
        for i in group:
            nospam_c = unique_nospam_circuits[i]
            for orig_i in circuits_by_unique_nospam_circuits[nospam_c]:  # orig circuits that add SPAM to nospam_c
                observed_outcomes = None if (dataset is None) else dataset[ds_circuits[orig_i]].outcomes
                expc_outcomes = unique_complete_circuits[orig_i].expand_instruments_and_separate_povm(
                    model_shlp, observed_outcomes)

                for sep_povm_c, outcomes in expc_outcomes.items():
                    prep_lbl = sep_povm_c.circuit_without_povm[0]
                    exp_nospam_c = sep_povm_c.circuit_without_povm[1:]  # sep_povm_c *always* has prep lbl
                    spam_tuples = [(prep_lbl, elabel) for elabel in sep_povm_c.full_effect_labels]
                    outcome_by_spamtuple = _collections.OrderedDict([(st, (outcome, orig_i))
                                                                     for st, outcome in zip(spam_tuples, outcomes)])

                    if exp_nospam_c not in expanded_nospam_circuit_outcomes:
                        expanded_nospam_circuit_outcomes[exp_nospam_c] = outcome_by_spamtuple
                    else:
                        expanded_nospam_circuit_outcomes[exp_nospam_c].update(outcome_by_spamtuple)

        expanded_nospam_circuits = _collections.OrderedDict(
            [(i, cir) for i, cir in enumerate(expanded_nospam_circuit_outcomes.keys())])
        self.tree = _EvalTree.create(expanded_nospam_circuits)
        self._num_nonscratch_tree_items = len(expanded_nospam_circuits)  # put this in EvalTree?

        # self.tree's elements give instructions for evaluating ("caching") no-spam quantities (e.g. products).
        # Now we assign final element indices to the circuit outcomes corresponding to a given no-spam ("tree")
        # quantity plus a spam-tuple. We order the final indices so that all the outcomes corresponding to a
        # given spam-tuple are contiguous.

        tree_indices_by_spamtuple = _collections.OrderedDict()  # "tree" indices index expanded_nospam_circuits
        for i, c in expanded_nospam_circuits.items():
            for spam_tuple in expanded_nospam_circuit_outcomes[c].keys():
                if spam_tuple not in tree_indices_by_spamtuple: tree_indices_by_spamtuple[spam_tuple] = []
                tree_indices_by_spamtuple[spam_tuple].append(i)

        #Assign element indices, starting at `offset`
        # now that we know how many of each spamtuple there are, assign final element indices.
        local_offset = 0
        self.indices_by_spamtuple = _collections.OrderedDict()  # values are (element_indices, tree_indices) tuples.
        for spam_tuple, tree_indices in tree_indices_by_spamtuple.items():
            self.indices_by_spamtuple[spam_tuple] = (slice(local_offset, local_offset + len(tree_indices)),
                                                     _slct.list_to_slice(tree_indices, array_ok=True))
            local_offset += len(tree_indices)
            #TODO: allow tree_indices to be None or a slice?

        element_slice = slice(offset, offset + local_offset)  # *global* (of parent layout) element-index slice
        num_elements = local_offset

        for spam_tuple, (element_indices, tree_indices) in self.indices_by_spamtuple.items():
            for elindex, tree_index in zip(_slct.indices(element_indices), _slct.to_array(tree_indices)):
                outcome_by_spamtuple = expanded_nospam_circuit_outcomes[expanded_nospam_circuits[tree_index]]
                outcome, orig_i = outcome_by_spamtuple[spam_tuple]
                elindex_outcome_tuples[orig_i].append((offset + elindex, outcome))  # put *global* element indices here

        super().__init__(element_slice, num_elements)

    def nonscratch_cache_view(self, a, axis=None):
        """
        Create a view of array `a` restricting it to only the *final* results computed by this tree.

        This need not be the entire array because there could be intermediate results
        (e.g. "scratch space") that are excluded.

        Parameters
        ----------
        a : ndarray
            An array of results computed using this EvalTree,
            such that the `axis`-th dimension equals the full
            length of the tree.  The other dimensions of `a` are
            unrestricted.

        axis : int, optional
            Specified the axis along which the selection of the
            final elements is performed. If None, than this
            selection if performed on flattened `a`.

        Returns
        -------
        ndarray
            Of the same shape as `a`, except for along the
            specified axis, whose dimension has been reduced
            to filter out the intermediate (non-final) results.
        """
        if axis is None:
            return a[0:self._num_nonscratch_tree_items]
        else:
            sl = [slice(None)] * a.ndim
            sl[axis] = slice(0, self._num_nonscratch_tree_items)
            ret = a[tuple(sl)]
            assert(ret.base is a or ret.base is a.base)  # check that what is returned is a view
            assert(ret.size == 0 or _np.may_share_memory(ret, a))
            return ret

    @property
    def cache_size(self):
        return len(self.tree)


class MatrixCOPALayout(_DistributableCOPALayout):
    """
    TODO: update docstring

    An Evaluation Tree that structures circuits for efficient multiplication of process matrices.

    MatrixEvalTree instances create and store the decomposition of a list of circuits into
    a sequence of 2-term products of smaller strings.  Ideally, this sequence would
    prescribe the way to obtain the entire list of circuits, starting with just the single
    gates, using the fewest number of multiplications, but this optimality is not
    guaranteed.

    Parameters
    ----------
    items : list, optional
        Initial items.  This argument should only be used internally
        in the course of serialization.

    num_strategy_subcomms : int, optional
        The number of processor groups (communicators) to divide the "atomic" portions
        of this strategy (a circuit probability array layout) among when calling `distribute`.
        By default, the communicator is not divided.  This default behavior is fine for cases
        when derivatives are being taken, as multiple processors are used to process differentiations
        with respect to different variables.  If no derivaties are needed, however, this should be
        set to (at least) the number of processors.
    """

    def __init__(self, circuits, model_shlp, dataset=None, max_sub_tree_size=None,
                 num_sub_trees=None, additional_dimensions=(), verbosity=0):

        #OUTDATED: TODO - revise this:
        # 1. pre-process => get complete circuits => spam-tuples list for each no-spam circuit (no expanding yet)
        # 2. decide how to divide no-spam circuits into groups corresponding to sub-strategies
        #    - create tree of no-spam circuits (may contain instruments, etc, just not SPAM)
        #    - heuristically find groups of circuits that meet criteria
        # 3. separately create a tree of no-spam expanded circuits originating from each group => self.atoms
        # 4. assign "cache" and element indices so that a) all elements of a tree are contiguous
        #    and b) elements with the same spam-tuple are continguous.
        # 5. initialize base class with given per-original-circuit element indices.

        unique_circuits, to_unique = self._compute_unique_circuits(circuits)
        aliases = circuits.op_label_aliases if isinstance(circuits, _CircuitList) else None
        ds_circuits = _lt.apply_aliases_to_circuits(unique_circuits, aliases)
        unique_complete_circuits = [model_shlp.complete_circuit(c) for c in unique_circuits]

        circuits_by_unique_nospam_circuits = _collections.OrderedDict()
        for i, c in enumerate(unique_complete_circuits):
            _, nospam_c, _ = model_shlp.split_circuit(c)
            if nospam_c in circuits_by_unique_nospam_circuits:
                circuits_by_unique_nospam_circuits[nospam_c].append(i)
            else:
                circuits_by_unique_nospam_circuits[nospam_c] = [i]
        unique_nospam_circuits = list(circuits_by_unique_nospam_circuits.keys())

        circuit_tree = _EvalTree.create(unique_nospam_circuits)
        groups = circuit_tree.find_splitting(len(unique_nospam_circuits),
                                             max_sub_tree_size, num_sub_trees, verbosity)  # a list of tuples/sets?
        # (elements of `groups` contain indices into `unique_nospam_circuits`)

        atoms = []
        elindex_outcome_tuples = _collections.OrderedDict([
            (orig_i, list()) for orig_i in range(len(unique_circuits))])

        offset = 0
        for group in groups:
            atoms.append(_MatrixCOPALayoutAtom(unique_complete_circuits, unique_nospam_circuits,
                                               circuits_by_unique_nospam_circuits, ds_circuits, group,
                                               model_shlp, dataset, offset, elindex_outcome_tuples))
            offset += atoms[-1].num_elements

        super().__init__(circuits, unique_circuits, to_unique, elindex_outcome_tuples, unique_complete_circuits,
                         atoms, additional_dimensions)
