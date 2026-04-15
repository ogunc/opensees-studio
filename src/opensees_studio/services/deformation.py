"""Adapt analysis results to the renderer's deformation API.

These functions know how OpenSees stores results and how the renderer
expects per-node displacement vectors. They live here (services/) to
keep both core/ and views/ ignorant of each other.
"""

from __future__ import annotations

import math

import numpy as np

from opensees_studio.core import Project
from opensees_studio.services.results import ModalResults, StaticResults
from opensees_studio.views.canvas3d.model_renderer import DeformationSource


def static_to_deformation(
    project: Project, results: StaticResults, *,
    step: int = -1, scale: float = 1.0,
) -> DeformationSource:
    """Build a DeformationSource from a static analysis's nodal displacements.

    Only the first 3 DOFs (Ux, Uy, Uz) are used — rotational DOFs don't
    move the joint itself. Missing nodes (no displacement recorded) are
    treated as zero displacement.
    """
    n_nodes = len(project.nodes)
    disp = np.zeros((n_nodes, 3), dtype=float)
    node_id_to_row = {n.id: i for i, n in enumerate(project.nodes)}
    for nid, history in results.node_disp.items():
        if nid not in node_id_to_row:
            continue
        snapshot = np.asarray(history[step])
        # Take only translation DOFs (first 2 in 2D, first 3 in 3D).
        n_take = min(3, snapshot.shape[0])
        disp[node_id_to_row[nid], :n_take] = snapshot[:n_take]
    return DeformationSource(displacements=disp,
                             node_id_to_row=node_id_to_row, scale=scale)


def modal_to_deformation(
    project: Project, results: ModalResults, *,
    mode: int = 0, scale: float = 1.0, phase: float = 1.0,
) -> DeformationSource:
    """Build a DeformationSource from a modal analysis's mode shape.

    ``mode`` is 0-indexed (0 = first mode). Internally OpenSees uses
    1-indexed mode numbers. ``phase`` should be in [-1, 1] and is
    multiplied through the eigenvector amplitude — typically a
    sin(2π t / T) loop drives this for animation.
    """
    n_nodes = len(project.nodes)
    disp = np.zeros((n_nodes, 3), dtype=float)
    node_id_to_row = {n.id: i for i, n in enumerate(project.nodes)}

    mode_number = mode + 1  # mode_shapes is 1-indexed
    if mode_number not in results.mode_shapes:
        return DeformationSource(displacements=disp,
                                 node_id_to_row=node_id_to_row, scale=scale)

    eigvec = results.mode_shapes[mode_number]   # dict: nid → np.ndarray of DOF values
    for nid, vec in eigvec.items():
        if nid not in node_id_to_row:
            continue
        v = np.asarray(vec)
        n_take = min(3, v.shape[0])
        disp[node_id_to_row[nid], :n_take] = v[:n_take] * phase

    # Normalize the eigenvector to a fraction of the model's bounding box
    # so the user-supplied scale is meaningful (e.g. scale=1.0 → 5% of bbox).
    coords = np.array([n.coords for n in project.nodes], dtype=float)
    if len(coords) >= 2:
        bbox = float(np.linalg.norm(coords.max(axis=0) - coords.min(axis=0)))
    else:
        bbox = 1.0
    max_amp = float(np.max(np.abs(disp)))
    if max_amp > 0 and bbox > 0:
        norm_factor = (bbox * 0.05) / max_amp
        disp *= norm_factor

    return DeformationSource(displacements=disp,
                             node_id_to_row=node_id_to_row, scale=scale)


def transient_to_deformation_at_step(
    project: Project, results, *, step: int = 0, scale: float = 1.0,
) -> DeformationSource:
    """Build a DeformationSource from a transient analysis at one step.

    Reads `node_disp_history` for every node and takes the row at `step`.
    Auto-scales like the modal helper so the deformation is visible.
    """
    n_nodes = len(project.nodes)
    disp = np.zeros((n_nodes, 3), dtype=float)
    node_id_to_row = {n.id: i for i, n in enumerate(project.nodes)}

    for n in project.nodes:
        try:
            history = results.node_disp_history(n.id)
        except Exception:
            continue
        if step >= history.shape[0]:
            step = history.shape[0] - 1
        snapshot = history[step]
        n_take = min(3, snapshot.shape[0])
        disp[node_id_to_row[n.id], :n_take] = snapshot[:n_take]

    # Normalize like modal so scale=1.0 is visible.
    coords = np.array([nd.coords for nd in project.nodes], dtype=float)
    if len(coords) >= 2:
        bbox = float(np.linalg.norm(coords.max(axis=0) - coords.min(axis=0)))
    else:
        bbox = 1.0
    max_amp = float(np.max(np.abs(disp)))
    if max_amp > 0 and bbox > 0:
        norm_factor = (bbox * 0.10) / max_amp
        disp *= norm_factor

    return DeformationSource(displacements=disp,
                             node_id_to_row=node_id_to_row, scale=scale)


def linear_static_auto_scale(project: Project, results: StaticResults) -> float:
    """Suggest a scale factor that makes the displacement visible.

    Returns a multiplier such that the largest absolute disp ~ 5% of the
    model's bounding box diagonal. Falls back to 1.0 if results are empty
    or geometry is degenerate.
    """
    coords = np.array([n.coords for n in project.nodes], dtype=float)
    if len(coords) < 2:
        return 1.0
    bbox = float(np.linalg.norm(coords.max(axis=0) - coords.min(axis=0)))
    if bbox <= 0:
        return 1.0

    max_disp = 0.0
    for history in results.node_disp.values():
        snapshot = np.asarray(history[-1])
        max_disp = max(max_disp, float(np.max(np.abs(snapshot[:3]))))
    if max_disp <= 0:
        return 1.0
    return (bbox * 0.05) / max_disp
