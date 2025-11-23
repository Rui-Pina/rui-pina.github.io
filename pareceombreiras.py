import bpy
from mathutils import Vector

GARMENT_FILE_PATH = "/Users/rui.pina/Documents/MS/Tickets/CHDPD-377/YARN TEST2.glb"
HANGER_FILE_PATH  = "/Users/rui.pina/Documents/MS/Tickets/CHDPD-377/MS_Top-Hanger-OLDER.glb"


# -------------------------------------------------------------
# Helper Functions
# -------------------------------------------------------------

def import_gltf(filepath):
    """Import a GLTF file and return the list of newly created objects."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=filepath)
    after = set(bpy.data.objects)
    return list(after - before)


def select_objects(objects):
    """Select only the given objects and set the first one as active."""
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        obj.select_set(True)
    if objects:
        bpy.context.view_layer.objects.active = objects[0]


def get_world_bbox_z(obj):
    """Return minZ and maxZ of object's bounding box in *world space*."""
    coords = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    zs = [c.z for c in coords]
    return min(zs), max(zs)


def get_objects_z_range(objs):
    """Return minZ and maxZ across multiple objects."""
    min_z = float("inf")
    max_z = float("-inf")

    for obj in objs:
        obj_min, obj_max = get_world_bbox_z(obj)
        min_z = min(min_z, obj_min)
        max_z = max(max_z, obj_max)

    return min_z, max_z


def calculate_hanger_translation_z(garment_objs, hanger_objs):
    """
    Compute vertical offset:
    1. Align hanger bottom with garment collar height.
    2. Add fixed correction to compensate hanger model origin.
    """

    garment_ref_z = max(obj.location.z for obj in garment_objs)
    hanger_min_z, _ = get_objects_z_range(hanger_objs)

    # Dynamic alignment
    offset = garment_ref_z - hanger_min_z

    # Fixed hanger correction (same as your previous value)
    FIXED_HANGER_Z_CORRECTION = -0.851134
    offset += FIXED_HANGER_Z_CORRECTION

    return offset


def apply_translation_z(offset):
    """Translate active objects in Z by the computed offset."""
    bpy.ops.transform.translate(
        value=(0.0, 0.0, offset),
        orient_type='GLOBAL',
        constraint_axis=(False, False, True),
        release_confirm=True
    )


def scale_hanger_width(scale_x=0.84189):
    """Scale the hanger horizontally to fit better inside the garment."""
    bpy.ops.transform.resize(
        value=(scale_x, 1.0, 1.0),
        orient_type='GLOBAL',
        constraint_axis=(True, False, False),
        mirror=False,
        use_proportional_edit=False
    )


def setup_collision_objects(hanger_objs):
    """Add collision physics to hanger objects."""
    for hanger in hanger_objs:
        if hanger.type != 'MESH':
            continue

        # Remove existing collision modifiers if present
        for mod in list(hanger.modifiers):
            if mod.type == 'COLLISION':
                hanger.modifiers.remove(mod)

        # Add new collision modifier
        collision_mod = hanger.modifiers.new(name="Collision", type='COLLISION')
        collision_mod.settings.thickness_outer = 0.02
        collision_mod.settings.cloth_friction = 5.0
        collision_mod.settings.damping = 0.1

        # "Remove single sided" – disable culling so both sides collide
        if hasattr(collision_mod.settings, "use_culling"):
            collision_mod.settings.use_culling = False


# -------------------------------------------------------------
# Garment processing (join, merge by distance, pin group)
# -------------------------------------------------------------

def join_garment_objects(garment_objs):
    """
    Join all garment pattern objects into a single mesh object.
    Returns the joined garment object.
    """
    if not garment_objs:
        return None

    select_objects(garment_objs)
    bpy.ops.object.join()
    # After join, active object is the joined one
    joined = bpy.context.view_layer.objects.active
    return joined


def clean_garment_mesh(garment_obj, merge_distance=0.0001):
    """
    Enter Edit Mode, select all vertices and Merge by Distance
    (equivalent to remove_doubles).
    """
    if garment_obj is None or garment_obj.type != 'MESH':
        return

    bpy.context.view_layer.objects.active = garment_obj
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')

    # In newer Blender this is "merge_by_distance", but operator name is still:
    bpy.ops.mesh.remove_doubles(threshold=merge_distance)

    bpy.ops.object.mode_set(mode='OBJECT')


def create_shoulder_pin_group(garment_obj, group_name="PinGroup"):
    """
    Pick shoulder-mid vertices:
    The target area is the shoulder 'meat' region,
    not collar, not outer arm, not back.
    """
    if garment_obj is None or garment_obj.type != 'MESH':
        return None

    mesh = garment_obj.data

    # Remove old
    if group_name in garment_obj.vertex_groups:
        garment_obj.vertex_groups.remove(garment_obj.vertex_groups[group_name])
    vg = garment_obj.vertex_groups.new(name=group_name)

    verts = mesh.vertices

    # ---- 1. Get top third of garment (Z filtering) ----
    all_z = [v.co.z for v in verts]
    max_z = max(all_z)
    min_z = min(all_z)
    z_cut = min_z + (max_z - min_z) * 0.65  # top 35% of height

    top_verts = [v for v in verts if v.co.z >= z_cut]

    # ---- Split into left and right shoulders ----
    left = [v for v in top_verts if v.co.x < 0]
    right = [v for v in top_verts if v.co.x > 0]

    if not left or not right:
        return vg.name

    # ---- 2. Cluster each shoulder inward ----
    def pick_centroid_vertex(shoulder_verts):
        xs = [v.co.x for v in shoulder_verts]
        ys = [v.co.y for v in shoulder_verts]

        x_mid = (min(xs) + max(xs)) / 2
        y_mid = (min(ys) + max(ys)) / 2

        # This is the centroid target
        target = Vector((x_mid, y_mid, max_z))

        # Pick vertex closest to centroid, giving priority to high Z
        best = min(
            shoulder_verts,
            key=lambda v: (v.co - target).length + (max_z - v.co.z) * 0.1
        )
        return best

    left_v = pick_centroid_vertex(left)
    right_v = pick_centroid_vertex(right)

    vg.add([left_v.index, right_v.index], 1.0, 'REPLACE')

    return vg.name

def setup_cloth_simulation(garment_obj, pin_group_name=None):
    """
    Set up cloth simulation for the joined garment
    with a vertex group used as pin group (vertex_group_mass).
    Softer / chill settings as before.
    """
    if garment_obj is None or garment_obj.type != 'MESH':
        return

    # Remove existing cloth modifiers
    for mod in list(garment_obj.modifiers):
        if mod.type == 'CLOTH':
            garment_obj.modifiers.remove(mod)

    cloth = garment_obj.modifiers.new(name="Cloth", type='CLOTH')

    # --- Softer / chill settings ---
    cloth.settings.quality = 8  # you had 8 in your manual test
    cloth.settings.mass = 0.3
    cloth.settings.air_damping = 1.0

    cloth.settings.tension_stiffness = 15
    cloth.settings.compression_stiffness = 15
    cloth.settings.shear_stiffness = 5
    cloth.settings.bending_stiffness = 0.5

    cloth.settings.tension_damping = 5
    cloth.settings.compression_damping = 5
    cloth.settings.shear_damping = 5
    cloth.settings.bending_damping = 0.5

    cloth.settings.effector_weights.gravity = 1.0

    # Collision settings
    cloth.collision_settings.use_collision = True
    cloth.collision_settings.distance_min = 0.010
    cloth.collision_settings.collision_quality = 2
    cloth.collision_settings.impulse_clamp = 0
    cloth.collision_settings.use_self_collision = False

    # Pin group for shape
    if pin_group_name:
        cloth.settings.vertex_group_mass = pin_group_name


# -------------------------------------------------------------
# Operator
# -------------------------------------------------------------

class OBJECT_OT_move_hanger(bpy.types.Operator):
    bl_idname = "object.move_hanger_exact"
    bl_label = "Move Hanger with Cloth"
    bl_options = {'REGISTER', 'UNDO'}

    def import_garment(self):
        """Import garment."""
        objs = import_gltf(GARMENT_FILE_PATH)
        return objs

    def import_hanger(self):
        """Import hanger and return new objects."""
        objs = import_gltf(HANGER_FILE_PATH)
        if not objs:
            self.report({'ERROR'}, "No hanger imported")
            return None
        return objs

    def execute(self, context):

        # ---------------------------------------------------------
        # 1. Import garment, join pieces, clean, create pin group
        # ---------------------------------------------------------
        garment_objs = self.import_garment()
        if not garment_objs:
            self.report({'ERROR'}, "No garment imported")
            return {'CANCELLED'}

        joined_garment = join_garment_objects(garment_objs)
        clean_garment_mesh(joined_garment, merge_distance=0.0001)
        pin_group_name = create_shoulder_pin_group(joined_garment, group_name="Group")

        setup_cloth_simulation(joined_garment, pin_group_name=pin_group_name)

        # ---------------------------------------------------------
        # 2. Import hanger, move inside garment, scale, collision
        # ---------------------------------------------------------
        hanger_objs = self.import_hanger()
        if not hanger_objs:
            return {'CANCELLED'}

        # Select hanger so translation and scale apply to it
        select_objects(hanger_objs)

        # Scale hanger width to fit inside garment
        scale_hanger_width(scale_x=0.787532)  # from your manual steps

        # Compute dynamic offset based on garment collar
        offset = calculate_hanger_translation_z([joined_garment], hanger_objs)

        # Apply precise translation
        apply_translation_z(offset)

        # Set up physics simulation for hanger (collision, no culling)
        setup_collision_objects(hanger_objs)

        # ---------------------------------------------------------
        # 3. Scene / timeline
        # ---------------------------------------------------------
        context.scene.frame_set(1)
        context.scene.frame_end = 80  # 80 steps as you mentioned
        
        # ---------------------------------------------------------
        # 4. WHEN READY: Auto-run simulation (play through timeline)
        # ---------------------------------------------------------
        #scene = bpy.context.scene
        #for frame in range(scene.frame_start, scene.frame_end + 1):
        #    scene.frame_set(frame)

        self.report(
            {'INFO'},
            "Garment joined, cleaned, pinned at shoulders; hanger positioned with cloth sim ready. "
            "Press SPACEBAR to run simulation."
        )
        return {'FINISHED'}


# -------------------------------------------------------------
# Additional Operator to Apply Simulation
# -------------------------------------------------------------

class OBJECT_OT_apply_cloth(bpy.types.Operator):
    bl_idname = "object.apply_cloth_simulation"
    bl_label = "Apply Cloth Simulation"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        applied_count = 0
        for obj in context.scene.objects:
            if obj.type == 'MESH':
                for mod in obj.modifiers:
                    if mod.type == 'CLOTH':
                        context.view_layer.objects.active = obj
                        bpy.ops.object.modifier_apply(modifier=mod.name)
                        applied_count += 1
                        break
        
        self.report({'INFO'}, f"Applied cloth simulation to {applied_count} object(s)")
        return {'FINISHED'}


# -------------------------------------------------------------
# UI Panel
# -------------------------------------------------------------

class VIEW3D_PT_move_hanger(bpy.types.Panel):
    bl_label = "Garment on Hanger"
    bl_idname = "VIEW3D_PT_move_hanger"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Garment'

    def draw(self, context):
        layout = self.layout
        
        layout.label(text="Setup:")
        layout.operator("object.move_hanger_exact")
        
        layout.separator()
        layout.label(text="Simulation:")
        layout.label(text="Press SPACEBAR to simulate")
        
        layout.separator()
        layout.label(text="Finalize:")
        layout.operator("object.apply_cloth_simulation")


# -------------------------------------------------------------
# Registration
# -------------------------------------------------------------

def register():
    bpy.utils.register_class(OBJECT_OT_move_hanger)
    bpy.utils.register_class(OBJECT_OT_apply_cloth)
    bpy.utils.register_class(VIEW3D_PT_move_hanger)


def unregister():
    bpy.utils.unregister_class(VIEW3D_PT_move_hanger)
    bpy.utils.unregister_class(OBJECT_OT_apply_cloth)
    bpy.utils.unregister_class(OBJECT_OT_move_hanger)


try:
    unregister()
except:
    pass

register()
bpy.ops.object.move_hanger_exact('EXEC_DEFAULT')