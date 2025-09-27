#ok. I found it. Rotate on the z axis. put the hinge around the armpit area. maybe middle of SLEEVE and SLEEVE_1. I want to do it only after the fold of the sleeves toward the collar object. I want to use the same strategy to then rotate it using a hinge.

# Blender 3.x/4.x — Fold sleeves toward a collar object or fold back in half
import bpy, math
import numpy as np

# ---------- math helpers ----------
def pca_axis(coords_centered):
    cov = np.cov(coords_centered.T)
    vals, vecs = np.linalg.eigh(cov)
    a = vecs[:, np.argmax(vals)]
    n = np.linalg.norm(a)
    return a / (n if n > 1e-12 else 1.0)

def rodrigues_rotate(v, axis, theta):
    a = axis / max(np.linalg.norm(axis), 1e-12)
    c, s = math.cos(theta), math.sin(theta)
    axv   = np.cross(a[None,:], v)
    adotv = (v @ a)[:,None]
    return v*c + axv*s + a[None,:]*(adotv*(1.0 - c))

def apply_mat(points, M4):
    ones = np.ones((points.shape[0], 1), dtype=np.float64)
    P = np.concatenate([points, ones], axis=1)
    Q = P @ M4.T
    return Q[:, :3]

def get_object_world_points(ob):
    M = np.array(ob.matrix_world, dtype=np.float64)
    if ob.type == 'MESH' and ob.data and len(ob.data.vertices) > 0:
        pts_local = np.array([v.co[:] for v in ob.data.vertices], dtype=np.float64)
    else:
        pts_local = np.array([list(v) for v in ob.bound_box], dtype=np.float64) if ob.bound_box else np.array([[0,0,0]], dtype=np.float64)
    return apply_mat(pts_local, M)

def safe_hinge(main_axis, target_dir):
    h = np.cross(main_axis, target_dir)
    n = np.linalg.norm(h)
    if n < 1e-8:
        h = np.cross(main_axis, np.array([1.0, 0.0, 0.0]))
        n = np.linalg.norm(h)
        if n < 1e-8:
            h = np.cross(main_axis, np.array([0.0, 1.0, 0.0]))
            n = np.linalg.norm(h)
    return h / max(n, 1e-12)

# ---------- sleeve fold ----------
def fold_single_sleeve_toward_collar(
    obj,
    collar_obj,
    fold_fraction=0.5,
    keep_band_ratio=0.01,
    end_window_ratio=0.15,
    min_verts=50,
    max_angle_deg=150.0,
    # NEW: object to tuck behind and amount to shift folded vertices
    tuck_front_obj=None,
    tuck_distance=0.0,
):
    if obj.type != 'MESH':
        raise RuntimeError(f"Object '{obj.name}' is not a mesh.")
    me = obj.data
    if len(me.vertices) < min_verts:
        raise RuntimeError(f"Object '{obj.name}' has too few vertices for analysis.")

    coords_L = np.array([v.co[:] for v in me.vertices], dtype=np.float64)
    c_L = coords_L.mean(axis=0)
    centered = coords_L - c_L

    axis_L = pca_axis(centered)

    u_all = centered @ axis_L
    u_min, u_max = float(np.min(u_all)), float(np.max(u_all))
    span = max(1e-12, (u_max - u_min))
    w = max(1e-6, end_window_ratio * span)

    low_mask  = (u_all <= (u_min + w))
    high_mask = (u_all >= (u_max - w))

    M  = np.array(obj.matrix_world, dtype=np.float64)
    Mi = np.array(obj.matrix_world.inverted(), dtype=np.float64)

    center_W = apply_mat(np.array([c_L]), M)[0]
    collar_pts_W = get_object_world_points(collar_obj)
    anchor = collar_pts_W[np.argmin(np.linalg.norm(collar_pts_W - center_W[None,:], axis=1))]

    if np.any(low_mask):
        low_centroid_W = apply_mat(coords_L[low_mask], M).mean(axis=0)
    else:
        low_centroid_W = center_W
    if np.any(high_mask):
        high_centroid_W = apply_mat(coords_L[high_mask], M).mean(axis=0)
    else:
        high_centroid_W = center_W

    dist_low  = np.linalg.norm(low_centroid_W  - anchor)
    dist_high = np.linalg.norm(high_centroid_W - anchor)

    if dist_low <= dist_high:
        shoulder_mask, cuff_mask_ends = low_mask, high_mask
    else:
        shoulder_mask, cuff_mask_ends = high_mask, low_mask

    u_all = centered @ axis_L
    u_shoulder_mean = float(np.mean(u_all[shoulder_mask])) if np.any(shoulder_mask) else u_min
    u_cuff_mean     = float(np.mean(u_all[cuff_mask_ends])) if np.any(cuff_mask_ends) else u_max
    if u_cuff_mean < u_shoulder_mean:
        axis_L = -axis_L
        u_all = centered @ axis_L
        u_min, u_max = float(np.min(u_all)), float(np.max(u_all))
        u_shoulder_mean = float(np.mean(u_all[shoulder_mask])) if np.any(shoulder_mask) else u_min
        u_cuff_mean     = float(np.mean(u_all[cuff_mask_ends])) if np.any(cuff_mask_ends) else u_max

    sleeve_len = max(1e-6, abs(u_cuff_mean - u_shoulder_mean))
    u_fold = u_shoulder_mean + fold_fraction * (u_cuff_mean - u_shoulder_mean)
    keep_band = max(1e-6, keep_band_ratio * sleeve_len)

    axis_W = (M[:3,:3] @ axis_L)
    axis_W /= max(1e-12, np.linalg.norm(axis_W))

    fold_center_W = apply_mat(np.array([c_L + u_fold * axis_L]), M)[0]
    target_dir = anchor - fold_center_W
    if np.linalg.norm(target_dir) < 1e-8:
        target_dir = np.array([0.0, 0.0, 1.0])
    target_dir /= max(1e-12, np.linalg.norm(target_dir))

    hinge_dir = safe_hinge(axis_W, target_dir)

    d = u_all - u_fold
    rotate_mask = (d > keep_band)
    if not np.any(rotate_mask):
        return
    idx = np.nonzero(rotate_mask)[0]

    verts_W_all = apply_mat(coords_L, M)
    verts_W_sel = verts_W_all[idx]
    r = verts_W_sel - fold_center_W[None,:]

    theta = math.radians(max_angle_deg)
    vW_pos = fold_center_W[None,:] + rodrigues_rotate(r, hinge_dir,  theta)
    vW_neg = fold_center_W[None,:] + rodrigues_rotate(r, hinge_dir, -theta)

    cuff_end_indices = np.nonzero(cuff_mask_ends)[0]
    cuff_end_indices = cuff_end_indices[np.isin(cuff_end_indices, idx)] if len(cuff_end_indices) else idx

    full_pos = verts_W_all.copy(); full_pos[idx] = vW_pos
    full_neg = verts_W_all.copy(); full_neg[idx] = vW_neg

    cuff_centroid_pos = full_pos[cuff_end_indices].mean(axis=0)
    cuff_centroid_neg = full_neg[cuff_end_indices].mean(axis=0)

    use_pos = np.linalg.norm(cuff_centroid_pos - anchor) > np.linalg.norm(cuff_centroid_neg - anchor)
    chosen = vW_pos if use_pos else vW_neg
    verts_W_all[idx] = chosen

    # ----------------- NEW: tuck folded vertices behind a front object -----------------
    if tuck_front_obj is not None:
        try:
            front_pts = get_object_world_points(tuck_front_obj)
            front_centroid = front_pts.mean(axis=0)
        except Exception:
            front_centroid = None

        # Determine a sensible tuck direction: from fold center toward front centroid,
        # otherwise fallback to the inverse of target_dir.
        if front_centroid is not None and np.linalg.norm(front_centroid - fold_center_W) > 1e-6:
            tuck_dir = front_centroid - fold_center_W
        else:
            tuck_dir = -target_dir  # move slightly away from collar (fallback)
        if np.linalg.norm(tuck_dir) < 1e-9:
            tuck_dir = np.array([0.0, 0.0, -1.0])
        tuck_dir /= np.linalg.norm(tuck_dir)

        # compute default tuck distance if user didn't give one
        if tuck_distance is None or tuck_distance <= 0.0:
            # default: 10% of distance from fold center to front centroid, or a small fixed amount
            if front_centroid is not None:
                default_dist = max(0.01, np.linalg.norm(front_centroid - fold_center_W) * 0.12)
            else:
                default_dist = 0.05
            td = default_dist
        else:
            td = tuck_distance

        # Apply translation only to the rotated (folded) vertices
        verts_W_all[idx] = verts_W_all[idx] + tuck_dir[None,:] * td
    # -------------------------------------------------------------------------------

    verts_L_new = apply_mat(verts_W_all, Mi)
    for i, v in enumerate(me.vertices):
        v.co[:] = verts_L_new[i]
    me.update()
    if hasattr(me, "calc_normals"):
        me.calc_normals()
        
def offset_armpit_center(center, offset_vec=(0, -0.02, 0)):
    """Translate armpit pivot slightly outward/backward."""
    return center + np.array(offset_vec, dtype=np.float64)        

# ---------- hinge rotate around armpit on Z ----------
def hinge_rotate_sleeve(
    obj,
    hinge_center=None,
    hinge_axis="Z",
    angle_deg=90.0,
    min_verts=50,
):
    if obj.type != 'MESH':
        raise RuntimeError(f"Object '{obj.name}' is not a mesh.")
    me = obj.data
    if len(me.vertices) < min_verts:
        raise RuntimeError(f"Object '{obj.name}' has too few vertices for hinge rotation.")

    coords_L = np.array([v.co[:] for v in me.vertices], dtype=np.float64)

    # world transforms
    M  = np.array(obj.matrix_world, dtype=np.float64)
    Mi = np.array(obj.matrix_world.inverted(), dtype=np.float64)

    verts_W_all = apply_mat(coords_L, M)

    # Default hinge center: mean of all verts if not specified
    if hinge_center is None:
        hinge_center = verts_W_all.mean(axis=0)

    # Axis in world space
    axis_idx = {"X":0, "Y":1, "Z":2}[hinge_axis.upper()]
    axis_L = np.zeros(3); axis_L[axis_idx] = 1.0
    axis_W = M[:3,:3] @ axis_L
    axis_W /= max(1e-12, np.linalg.norm(axis_W))

    # rotate all verts around hinge_center
    r = verts_W_all - hinge_center[None,:]
    theta = math.radians(angle_deg)
    verts_W_all = hinge_center[None,:] + rodrigues_rotate(r, axis_W, theta)

    # write back
    verts_L_new = apply_mat(verts_W_all, Mi)
    for i, v in enumerate(me.vertices):
        v.co[:] = verts_L_new[i]
    me.update()
    if hasattr(me, "calc_normals"):
        me.calc_normals()
        
def get_sleeve_armpit_center(obj, shoulder_mask=None):
    """Return the centroid of the shoulder-side (armpit) vertices in world space."""
    coords_L = np.array([v.co[:] for v in obj.data.vertices], dtype=np.float64)
    M = np.array(obj.matrix_world, dtype=np.float64)

    if shoulder_mask is not None and np.any(shoulder_mask):
        pts = coords_L[shoulder_mask]
    else:
        # fallback: just use all verts
        pts = coords_L

    return apply_mat(pts, M).mean(axis=0)
        

# ---------- back fold (bottom half rotates backward) ----------
def fold_back_in_half(
    obj,
    fold_axis_hint="Y",
    keep_band_ratio=0.01,
    min_verts=50,
    fold_direction="BACKWARD"
):
    print("\n=== FOLD BACK DEBUG ===")
    print(f"Object: {obj.name}")
    print(f"Fold axis hint: {fold_axis_hint}")
    print(f"Fold direction: {fold_direction}")

    if obj.type != 'MESH':
        raise RuntimeError(f"Object '{obj.name}' is not a mesh.")
    me = obj.data
    if len(me.vertices) < min_verts:
        raise RuntimeError(f"Object '{obj.name}' has too few vertices for analysis.")

    coords_L = np.array([v.co[:] for v in me.vertices], dtype=np.float64)
    axis_idx = {"X":0, "Y":1, "Z":2}[fold_axis_hint.upper()]
    u_all = coords_L[:, axis_idx]
    u_min, u_max = float(np.min(u_all)), float(np.max(u_all))
    u_mid = 0.5 * (u_min + u_max)
    span  = max(1e-6, u_max - u_min)
    keep_band = max(1e-6, keep_band_ratio * span)

    print(f"Axis index: {axis_idx}, u_min={u_min:.4f}, u_max={u_max:.4f}, u_mid={u_mid:.4f}")
    print(f"Span={span:.4f}, Keep band={keep_band:.4f}")

    # bottom-half selection
    mask = (u_all < u_mid - keep_band)
    idx = np.nonzero(mask)[0]
    print(f"Selected vertices for folding: {len(idx)} / {len(coords_L)}")
    if not len(idx):
        print("⚠️ No vertices selected, skipping fold.")
        return

    # world matrices
    M  = np.array(obj.matrix_world, dtype=np.float64)
    Mi = np.array(obj.matrix_world.inverted(), dtype=np.float64)

    # world-space rotation axis
    if axis_idx == 0:   # fold along X → rotate around Y
        rot_axis_L = np.array([0,1,0])
    else:               # fold along Y or Z → rotate around X
        rot_axis_L = np.array([1,0,0])
    rot_axis_W = M[:3,:3] @ rot_axis_L
    rot_axis_W /= np.linalg.norm(rot_axis_W)
    print(f"Rotation axis (local): {rot_axis_L}, (world): {rot_axis_W}")

    # world-space vertices
    verts_W_all = apply_mat(coords_L, M)
    verts_W_sel = verts_W_all[idx]

    # fold center
    fold_center_W = apply_mat(np.array([[*coords_L.mean(axis=0)]]), M)[0]
    r = verts_W_sel - fold_center_W[None,:]

    # choose theta based on direction
    if fold_direction.upper() == "BACKWARD":
        theta = math.radians(-182.5)
    else:
        theta = math.radians(172.5)

    print(f"Rotation angle (degrees): {math.degrees(theta):.2f}")

    verts_W_all[idx] = fold_center_W[None,:] + rodrigues_rotate(r, rot_axis_W, theta)

    # write back
    verts_L_new = apply_mat(verts_W_all, Mi)
    for i, v in enumerate(me.vertices):
        v.co[:] = verts_L_new[i]
    me.update()
    if hasattr(me, "calc_normals"):
        me.calc_normals()

    print(f"✅ Fold applied to {obj.name}")

# ---------- Blender operators ----------
class OBJECT_OT_fold_named_sleeves(bpy.types.Operator):
    """Fold sleeves named 'SLEEVE' and 'SLEEVE_1' toward a collar object ('NECK RIB')"""
    bl_idname = "object.fold_named_sleeves"
    bl_label = "Fold Named Sleeves"
    bl_options = {'REGISTER', 'UNDO'}

    sleeve_names: bpy.props.StringProperty(default="SLEEVE,SLEEVE_1")
    collar_name: bpy.props.StringProperty(default="NECK RIB")
    fold_fraction: bpy.props.FloatProperty(default=0.5, min=0.1, max=0.9)
    keep_band_ratio: bpy.props.FloatProperty(default=0.01, min=0.0, max=0.05)
    end_window_ratio: bpy.props.FloatProperty(default=0.15, min=0.05, max=0.4)
    max_angle_deg: bpy.props.FloatProperty(default=150.0, min=60.0, max=180.0)
    min_verts: bpy.props.IntProperty(default=50, min=10, max=100000)

    def execute(self, context):
        names = [n.strip() for n in self.sleeve_names.split(",") if n.strip()]
        sleeves = [bpy.data.objects.get(n) for n in names if bpy.data.objects.get(n)]
        collar = bpy.data.objects.get(self.collar_name)
        if not sleeves or collar is None:
            self.report({'ERROR'}, "Sleeves or collar not found.")
            return {'CANCELLED'}
        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for ob in sleeves:
            fold_single_sleeve_toward_collar(
                ob, collar,
                fold_fraction=self.fold_fraction,
                keep_band_ratio=self.keep_band_ratio,
                end_window_ratio=self.end_window_ratio,
                min_verts=self.min_verts,
                max_angle_deg=self.max_angle_deg,
            )
            
        sleeve = bpy.data.objects.get("SLEEVE")
        sleeve1 = bpy.data.objects.get("SLEEVE_1")

        if sleeve and sleeve1:
            # compute armpit centers for both sleeves
            armpit_sleeve  = get_sleeve_armpit_center(sleeve)
            armpit_sleeve1 = get_sleeve_armpit_center(sleeve1)

            # hinge = midpoint between both armpit centroids
            hinge_center = 0.5 * (armpit_sleeve + armpit_sleeve1)

            # apply hinge rotation on Z (or Y depending on your mesh orientation)
            hinge_rotate_sleeve(sleeve,  hinge_center=hinge_center, hinge_axis="Z", angle_deg=-90)
            hinge_rotate_sleeve(sleeve1, hinge_center=hinge_center, hinge_axis="Z", angle_deg= 90)


class OBJECT_OT_fold_back(bpy.types.Operator):
    """Fold a back or front object in half (bottom half rotates backward)"""
    bl_idname = "object.fold_back"
    bl_label = "Fold Back in Half"
    bl_options = {'REGISTER', 'UNDO'}

    back_name: bpy.props.StringProperty(default="BACK_3")
    front_name: bpy.props.StringProperty(default="FRONT_3")

    fold_axis: bpy.props.EnumProperty(
        name="Fold Axis",
        items=[("X","X","Fold along X"),("Y","Y","Fold along Y"),("Z","Z","Fold along Z")],
        default="Y"
    )
    keep_band_ratio: bpy.props.FloatProperty(default=0.01, min=0.0, max=0.05)
    min_verts: bpy.props.IntProperty(default=50, min=10, max=100000)
    fold_direction: bpy.props.EnumProperty(
        name="Fold Direction",
        items=[("FORWARD","Forward","Fold Forward"), ("BACKWARD","Backward","Fold Backward")],
        default="BACKWARD"
    )

    def execute(self, context):
        ob = bpy.data.objects.get(self.back_name)
        ft = bpy.data.objects.get(self.front_name)
        if ob is None:
            self.report({'ERROR'}, f"Back object '{self.back_name}' not found.")
            return {'CANCELLED'}
        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        fold_back_in_half(ob, fold_axis_hint=self.fold_axis, fold_direction=self.fold_direction)
        fold_back_in_half(ft, fold_axis_hint=self.fold_axis, fold_direction="FORWARD")
        
        return {'FINISHED'}

# ---------- menu/register ----------
def menu_func(self, context):
    self.layout.operator(OBJECT_OT_fold_named_sleeves.bl_idname)
    self.layout.operator(OBJECT_OT_fold_back.bl_idname)

def register():
    bpy.utils.register_class(OBJECT_OT_fold_named_sleeves)
    bpy.utils.register_class(OBJECT_OT_fold_back)
    bpy.types.VIEW3D_MT_object.append(menu_func)

def unregister():
    bpy.types.VIEW3D_MT_object.remove(menu_func)
    bpy.utils.unregister_class(OBJECT_OT_fold_back)
    bpy.utils.unregister_class(OBJECT_OT_fold_named_sleeves)

def _ensure_register():
    try:
        unregister()
    except Exception:
        pass
    register()
_ensure_register()