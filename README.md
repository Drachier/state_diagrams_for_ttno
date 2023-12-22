# State Diagrams to determine Tree Tensor Network Operators
## Installation
The project is coded fully in Python and can be installed using the included `pyproject.toml`-file.

## PyTreeNet
PyTreeNet is a currently unreleased python library to work with tree tensor network operators. The folder contains all the code required to run the examples and simulations shown in the main paper. There are mutiple parts to the library
- The main folder provides all the tree tensor network utility. One can construct such tensor networks, combine and split the notes in it, and perform different contractions relevant for tree tensor networks states, such as scalar products and canonicalisation.
- The `operator` folder contains all the required data structures to represent a Hamiltonian as a sum of tensor products, where the actual operators are given by a label and not an explicit array/matrix
- The `ttno` folder contains all the algorithms discussed in the main paper. The code contained allows the construction of a tree tensor network operator of a Hamiltonian via state diagrams or singular value decomposition for a given tree structure.
- The `special_ttn` folder contains the fork tensor product structure used in the main paper.

## Tests
The `test` folder contains unittests that test the entire pytreenet library. Every test file is self contained and can be run on its own.

## Experiments
The `Experiments` folder contains all the files used for obtaining the data and plots shown in the main paper.
- The jupyter notebook `example_TNNO.ipynb` shows the functionality of our algorithm for the toy Hamiltonian and for the open system Hamiltonian introduced in the paper.
- The two `.py` files can be executed using a terminal. The required argument is the filepath to which the data is saved in `h5py`-files. They randomly generate a given number of Hamiltonians and finds the bond dimension of the TTNO resulting from singular value decomposition and our state diagram algorithm and saves them into files.
- The `plotting_bond_dimension.ipynb` notebook is used to plot the results.
- All the data and plots are saved in the subfolder `data`.
