# Train Single-Routing Selection Problem (TSRSP) — Benchmark Repository

<p align="center">
  <img src="TSRSP_logo.png" alt="TSRSP Logo" width="400"/>
</p>

This repository contains the full benchmark dataset used in the work:

> **An exact approach for the Train Single-Routing Selection Problem**  
> Anna Livia Croella, Fabio Furini, Ivana Ljubić, Bianca Pascariu, Paola Pellegrini, Pablo San Segundo  
> Submitted, July 2025
> 
<br>

## 🧩 Problem Overview

The **Train Single-Routing Selection Problem (TSRSP)** arises in the context of real-time railway traffic management. It consists in selecting exactly one feasible route per train from a predefined set of alternatives, in such a way that:

- The total cost — including route-specific delays and delay-induced penalties from route interactions — is minimized;
- All selected routes are pairwise compatible.

This problem can be modeled as the search for a minimum-weight **k-clique** in a **k-partite compatibility graph**, where each vertex represents a route and each layer corresponds to a train. Compatibility is encoded by edges between vertices of distinct layers, with associated pairwise (pairing) costs.

In the referenced article, we:
- Introduce a novel and effective MILP formulation based on a compact linearization of a Binary Quadratic Programming (BQP) model;
- Propose a strengthening of the LP relaxation tailored to the TSRSP structure;
- Perform a detailed theoretical and computational comparison against existing formulations;
- Present the first optimal solutions for large-scale real-world instances of the TSRSP.
<br>


## 📁 Repository Structure

The repository is organized into the following main folders:

- [`data/`](./data/) — Contains all **benchmark instances** used in the computational experiments, including instance statistics and detailed descriptions of the input formats and directory structure for the **Rouen** and **Lille** railway networks.

- [`results/`](./results/) — Contains the **computational results** obtained for the tested formulations, including CPU time, LP relaxation and optimality gap distributions, and performance profiles for the **Rouen** railway networks. A summary of computational results for all instances and formulations is also available as an Excel file.

Each folder contains its own `README.md` file with further details.
<br>


## 📚 Citation

If you use this dataset in academic work, please cite:

```
@article{Croella2025TSRSP,
  title={An exact approach for the Train Single-Routing Selection Problem},
  author={Croella, A.L. and Furini, F. and Ljubić, I. and Pascariu, B. and Pellegrini, P. and San Segundo, P.},
  year={2025}
}
```
<br>

## 📬 Contact

For questions, feedback, or collaboration inquiries, please contact:

- **Anna Livia Croella** – [annalivia.croella@unimercatorum.it](mailto:annalivia.croella@unimercatorum.it)

