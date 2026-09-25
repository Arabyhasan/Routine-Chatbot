from OpenGL.GL import *
from OpenGL.GLUT import *
from OpenGL.GLU import *
import time
import math
import heapq
import random

window_width = 1440
window_height = 750

# Camera-related variables
camera_mode = 'fps'
fovY = 90  # Field of view
camera_pitch = 0


game_state = 'running'

mouse_center_x = window_width // 2
mouse_center_y = window_height // 2
cursor_locked = True
mouse_sensitivity = 0.25

current_time = time.time()
delta_time = None

player_pos = [0,100,200]
player_angle = 0
player_width = 20
player_height = 40

player_normal_movement_velocity = 200
player_forward_velocity_multiplier = 0.0
player_sideward_velocity_multiplier = 0.0
player_upward_velocity_multiplier = 0.0
player_acceleration = 4
player_gravity = 45
player_jump_force = 26

movement_keys_pressed = {'w': False, 's': False, 'a': False, 'd': False, 'space': False}


main_enemy_info = {'tile_pos': [50,50,2], 'health': 100, 'target': None, 'length': 40,'speed': 40 , 'target_tile': None, 'color': (1,1,0)}

weapon_length = 5
weapon_side_offset = 0


world_ground_level = 25
grid_dimension = (100,100)
tile_length = 10
tile_res = 1
grid_color = [0.2,0.4,0.4]
wall_cubeoid_res = 2
flashlight_tiles_radius = 20
flashlight_radius = tile_length * flashlight_tiles_radius
flashlight_radius_squared = flashlight_radius ** 2

weapon_bullet_ray_origin_pos = [0,0,0]
last_bullet_shoot_time = None
weapon_muzzle_pos = [0,0,0]
bullet_left = 40
health = 100

drone_collision_sphere_multiplier = 3
max_drone_that_can_follow = 4
total_drone_follwing_player = 0

is_minimap_visible = False

drones = []

tiles_dict = {}

bullets = []

def draw_tile(tile_x, tile_y, tile_z, tile_info_dict):
    tiles_dict[(tile_x, tile_y, tile_z)] = tile_info_dict

def draw_wall(wall_start_tile_x, wall_start_tile_y, wall_start_tile_z, wall_tile_width, wall_tile_length, wall_tile_height, wall_info_dict):
    global tiles_dict

    #right wall
    cur_tile_y = wall_start_tile_y
    while cur_tile_y < wall_start_tile_y + wall_tile_length:
        cur_tile_z = wall_start_tile_z
        while cur_tile_z < wall_start_tile_z + wall_tile_height:
            draw_tile(wall_start_tile_x, cur_tile_y, cur_tile_z, wall_info_dict)
            cur_tile_z += 1
        cur_tile_y += 1

    if not wall_tile_width == 1:
        #left wall
        cur_tile_y = wall_start_tile_y
        while cur_tile_y < wall_start_tile_y + wall_tile_length:
            cur_tile_z = wall_start_tile_z
            while cur_tile_z < wall_start_tile_z + wall_tile_height:
                draw_tile(wall_start_tile_x + wall_tile_width - 1, cur_tile_y, cur_tile_z, wall_info_dict)
                cur_tile_z += 1
            cur_tile_y += 1

    #top wall
    cur_tile_x = wall_start_tile_x
    while cur_tile_x < wall_start_tile_x + wall_tile_width:
        cur_tile_z = wall_start_tile_z
        while cur_tile_z < wall_start_tile_z + wall_tile_height:
            draw_tile(cur_tile_x, wall_start_tile_y, cur_tile_z, wall_info_dict)
            cur_tile_z += 1
        cur_tile_x += 1

    if not wall_tile_length == 1:
        #bottom wall
        cur_tile_x = wall_start_tile_x
        while cur_tile_x < wall_start_tile_x + wall_tile_width:
            cur_tile_z = wall_start_tile_z
            while cur_tile_z < wall_start_tile_z + wall_tile_height:
                draw_tile(cur_tile_x, wall_start_tile_y + wall_tile_length - 1, cur_tile_z, wall_info_dict)
                cur_tile_z += 1
            cur_tile_x += 1


    #floor
    cur_tile_y = wall_start_tile_y
    while cur_tile_y < wall_start_tile_y + wall_tile_length:
        cur_tile_x = wall_start_tile_x
        while cur_tile_x < wall_start_tile_x + wall_tile_width:
            draw_tile(cur_tile_x, cur_tile_y, wall_start_tile_z, wall_info_dict)
            cur_tile_x += 1
        cur_tile_y += 1


    if not wall_tile_height == 1:
        #ceiling
        cur_tile_y = wall_start_tile_y
        while cur_tile_y < wall_start_tile_y + wall_tile_length:
            cur_tile_x = wall_start_tile_x
            while cur_tile_x < wall_start_tile_x + wall_tile_width:
                draw_tile(cur_tile_x, cur_tile_y, wall_start_tile_z + wall_tile_height, wall_info_dict)
                cur_tile_x += 1
            cur_tile_y +=1


def draw_floor():
    for x in range(grid_dimension[0]):
        for y in range(grid_dimension[1]):
            draw_tile(x, y, 0, {'color': grid_color})

def is_tile_occupied(tile_x, tile_y, tile_z):
    return (tile_x, tile_y, tile_z) in tiles_dict

def get_tile_from_pos(pos_x, pos_y, pos_z):
    init_x = - (tile_length * grid_dimension[0]) / 2
    init_y = - (tile_length * grid_dimension[1]) / 2
    
    tile_x = int((pos_x - init_x)/tile_length)
    tile_y = int((pos_y - init_y)/tile_length)
    tile_z = int(pos_z / tile_length)

    return (tile_x, tile_y, tile_z)

def get_world_pos_from_tile(tile_x, tile_y, tile_z):
    world_start_pos_x = -(tile_length * grid_dimension[0]) / 2
    world_start_pos_y = -(tile_length * grid_dimension[1]) / 2

    world_x = world_start_pos_x + tile_x * tile_length + tile_length / 2
    world_y = world_start_pos_y + tile_y * tile_length + tile_length / 2
    world_z = tile_z * tile_length + tile_length / 2

    return (world_x, world_y, world_z)

def get_world_pos_from_tile(tile_x, tile_y, tile_z):
    world_start_pos_x = -(tile_length * grid_dimension[0]) / 2
    world_start_pos_y = -(tile_length * grid_dimension[1]) / 2

    world_x = world_start_pos_x + tile_x * tile_length + tile_length / 2
    world_y = world_start_pos_y + tile_y * tile_length + tile_length / 2
    world_z = tile_z * tile_length + tile_length / 2

    return [world_x, world_y, world_z]

def move_player(movement_vector_x, movement_vector_y, movement_vector_z):
    cur_x, cur_y, cur_z = player_pos
    new_x = cur_x + movement_vector_x
    new_y = cur_y + movement_vector_y
    new_z = cur_z + movement_vector_z

    #detect collision left side of body
    x = new_x + player_width / 2
    y = new_y
    z = new_z

    tile_x, tile_y, tile_z = get_tile_from_pos(x, y, z)
    if is_tile_occupied(tile_x, tile_y, tile_z):
        return

    #detect collision right side of body
    x = new_x - player_width / 2
    y = new_y
    z = new_z

    tile_x, tile_y, tile_z = get_tile_from_pos(x, y, z)
    if is_tile_occupied(tile_x, tile_y, tile_z):
        return

    #detect collision front side of body
    x = new_x
    y = new_y - player_width / 2
    z = new_z

    tile_x, tile_y, tile_z = get_tile_from_pos(x, y, z)
    if is_tile_occupied(tile_x, tile_y, tile_z):
        return

    #detect collision back side of body
    x = new_x
    y = new_y + player_width / 2
    z = new_z

    tile_x, tile_y, tile_z = get_tile_from_pos(x, y, z)
    if is_tile_occupied(tile_x, tile_y, tile_z):
        return

    # collision with grid boundary
    world_min_x = -(tile_length * grid_dimension[0]) / 2
    world_max_x = world_min_x + tile_length * grid_dimension[0]

    world_min_y = -(tile_length * grid_dimension[1]) / 2
    world_max_y = world_min_y + tile_length * grid_dimension[1]

    if new_x < world_min_x or new_x > world_max_x:
        return

    if new_y < world_min_y or new_y > world_max_y:
        return


    player_pos[0] = new_x
    player_pos[1] = new_y
    player_pos[2] = new_z

def is_player_grounded():
    # return player_pos[2] <= world_ground_level

    tile_x, tile_y, tile_z = get_tile_from_pos(player_pos[0], player_pos[1], player_pos[2] - player_height)
    return is_tile_occupied(tile_x, tile_y, tile_z) or player_pos[2] - player_height <= world_ground_level

def get_player_forward_vector():
    global player_angle
    x = math.sin(player_angle * math.pi / 180)
    y = - math.cos(player_angle * math.pi / 180)

    return (x,y)

def get_player_aim_vector():
    x = math.sin(player_angle * math.pi / 180) * math.cos(camera_pitch * math.pi/180)
    y = - math.cos(player_angle * math.pi / 180) * math.cos(camera_pitch * math.pi/180)
    z = math.sin(camera_pitch * math.pi/180)
    return (x,y,z)

def get_distance_squared(pos_1, pos_2):
    pos_1_x, pos_1_y, pos_1_z = pos_1
    pos_2_x, pos_2_y, pos_2_z = pos_2

    res = (pos_1_x - pos_2_x)**2 + (pos_1_y - pos_2_y)**2 + (pos_1_z - pos_2_z)**2
    return res

def get_adjusted_object_color(object_position, preferred_color):
    distance_from_player_squared = get_distance_squared(object_position, player_pos)
    brightness_value = (flashlight_radius_squared - distance_from_player_squared) / (flashlight_radius_squared + 0.75* distance_from_player_squared)
    return (preferred_color[0] * brightness_value, preferred_color[1] * brightness_value, preferred_color[2] * brightness_value)

def get_adjusted_illuminated_object_color(object_position, preferred_color):
    distance_from_player_squared = get_distance_squared(object_position, player_pos)
    brightness_value = (flashlight_radius_squared*4 - distance_from_player_squared) / (flashlight_radius_squared*4 + 0.75* distance_from_player_squared)
    return (preferred_color[0] * brightness_value, preferred_color[1] * brightness_value, preferred_color[2] * brightness_value)

def should_objected_be_rendered(object_pos):
    object_distance_from_player_squared = get_distance_squared(player_pos, object_pos)
    return object_distance_from_player_squared < flashlight_radius_squared

def should_illuminated_objected_be_rendered(object_pos):
    object_distance_from_player_squared = get_distance_squared(player_pos, object_pos)
    return object_distance_from_player_squared < flashlight_radius_squared * 4

def drawCrosshair():
    glMatrixMode(GL_PROJECTION)
    glPushMatrix()
    glLoadIdentity()
    gluOrtho2D(0, window_width, 0, window_height)

    glMatrixMode(GL_MODELVIEW)
    glPushMatrix()
    glLoadIdentity()

    glColor3f(1, 1, 1)

    glBegin(GL_LINES)

    cross_hair_len = 10
    # Horizontal
    glVertex2f(window_width/2 - cross_hair_len, window_height/2)
    glVertex2f(window_width/2 + cross_hair_len, window_height/2)

    # Vertical
    glVertex2f(window_width/2 , window_height/2 - cross_hair_len)
    glVertex2f(window_width/2 , window_height/2 + cross_hair_len)

    glEnd()

    glPopMatrix()

    glMatrixMode(GL_PROJECTION)
    glPopMatrix()

    glMatrixMode(GL_MODELVIEW)

def draw_minimap():

    """
    Draw a 2D top-down map.

    The minimap does NOT use the 3D camera.
    It uses an orthographic projection and draws small
    rectangles representing the grid.

    Because the minimap pauses the game, the map is static
    while it is displayed.
    """

    glMatrixMode(GL_PROJECTION)
    glPushMatrix()
    glLoadIdentity()
    gluOrtho2D(0, window_width, 0, window_height)

    glMatrixMode(GL_MODELVIEW)
    glPushMatrix()
    glLoadIdentity()


    minimap_size = 400
    minimap_x = 20
    minimap_y = window_height - minimap_size - 20

    pixels_per_tile = minimap_size / grid_dimension[0]

    # Background.
    glColor3f(0.8, 0.8, 0.8)

    glBegin(GL_LINE_LOOP)
    glVertex2f(minimap_x, minimap_y)
    glVertex2f(minimap_x + minimap_size, minimap_y)
    glVertex2f(minimap_x + minimap_size, minimap_y + minimap_size)
    glVertex2f(minimap_x, minimap_y + minimap_size)
    glEnd()

    for (tile_x, tile_y, tile_z), tile_info in tiles_dict.items():
        if tile_z == 0: continue

        x = minimap_x + (grid_dimension[0] - tile_x) * pixels_per_tile
        y = minimap_y + (grid_dimension[1] - tile_y) * pixels_per_tile

        glColor3f(0.8, 0.8, 0.8)

        glBegin(GL_QUADS)
        glVertex2f(x, y)
        glVertex2f(x + pixels_per_tile, y)
        glVertex2f(x + pixels_per_tile, y + pixels_per_tile)
        glVertex2f(x, y + pixels_per_tile)
        glEnd()

    # Player.
    player_tile_x, player_tile_y, player_tile_z = get_tile_from_pos(
        player_pos[0],
        player_pos[1],
        player_pos[2]
    )

    player_map_x = (
        minimap_x
        + (grid_dimension[0] - (player_tile_x + 0.5)) * pixels_per_tile
    )

    player_map_y = (
        minimap_y
        + (grid_dimension[1] - (player_tile_y + 0.5)) * pixels_per_tile
    )

    player_marker_size = 6

    glColor3f(0, 1, 0)

    glBegin(GL_QUADS)

    glVertex2f(
        player_map_x - player_marker_size,
        player_map_y - player_marker_size
    )
    glVertex2f(
        player_map_x + player_marker_size,
        player_map_y - player_marker_size
    )
    glVertex2f(
        player_map_x + player_marker_size,
        player_map_y + player_marker_size
    )
    glVertex2f(
        player_map_x - player_marker_size,
        player_map_y + player_marker_size
    )

    glEnd()

    # Main enemy.
    enemy_x, enemy_y, enemy_z = main_enemy_info['real_pos']

    enemy_tile_x, enemy_tile_y, enemy_tile_z = get_tile_from_pos(
        enemy_x,
        enemy_y,
        enemy_z
    )

    enemy_map_x = (
        minimap_x
        + (grid_dimension[0] - (enemy_tile_x + 0.5)) * pixels_per_tile
    )

    enemy_map_y = (
        minimap_y
        + (grid_dimension[1] - (enemy_tile_y + 0.5)) * pixels_per_tile
    )

    glColor3f(1, 0, 0)

    glBegin(GL_QUADS)

    glVertex2f(
        enemy_map_x - player_marker_size,
        enemy_map_y - player_marker_size
    )
    glVertex2f(
        enemy_map_x + player_marker_size,
        enemy_map_y - player_marker_size
    )
    glVertex2f(
        enemy_map_x + player_marker_size,
        enemy_map_y + player_marker_size
    )
    glVertex2f(
        enemy_map_x - player_marker_size,
        enemy_map_y + player_marker_size
    )

    glEnd()

    # Drones.
    glColor3f(0, 0, 1)

    for drone in drones:

        drone_x, drone_y, drone_z = drone['current_real_pos']

        drone_tile_x, drone_tile_y, drone_tile_z = get_tile_from_pos(
            drone_x,
            drone_y,
            drone_z
        )

        drone_map_x = (
            minimap_x
            + (grid_dimension[0] - (drone_tile_x + 0.5)) * pixels_per_tile
        )

        drone_map_y = (
            minimap_y
            + (grid_dimension[1] - (drone_tile_y + 0.5)) * pixels_per_tile
        )

        drone_marker_size = 4

        glBegin(GL_QUADS)

        glVertex2f(
            drone_map_x - drone_marker_size,
            drone_map_y - drone_marker_size
        )
        glVertex2f(
            drone_map_x + drone_marker_size,
            drone_map_y - drone_marker_size
        )
        glVertex2f(
            drone_map_x + drone_marker_size,
            drone_map_y + drone_marker_size
        )
        glVertex2f(
            drone_map_x - drone_marker_size,
            drone_map_y + drone_marker_size
        )

        glEnd()

    draw_text(
        minimap_x,
        minimap_y - 25,
        "MINIMAP - M to close"
    )

    glMatrixMode(GL_PROJECTION)
    glPopMatrix()

    glMatrixMode(GL_MODELVIEW)
    glPopMatrix()



def draw_text(x, y, text, font=GLUT_BITMAP_HELVETICA_18):
    glColor3f(1,1,1)
    glMatrixMode(GL_PROJECTION)
    glPushMatrix()
    glLoadIdentity()
    
    # Set up an orthographic projection that matches window coordinates
    gluOrtho2D(0, window_width, 0, window_height)  # left, right, bottom, top

    
    glMatrixMode(GL_MODELVIEW)
    glPushMatrix()
    glLoadIdentity()
    
    # Draw text at (x, y) in screen coordinates
    glRasterPos2f(x, y)
    for ch in text:
        glutBitmapCharacter(font, ord(ch))
    
    # Restore original projection and modelview matrices
    glPopMatrix()
    glMatrixMode(GL_PROJECTION)
    glPopMatrix()
    glMatrixMode(GL_MODELVIEW)


def render_tiles():
    global tiles_dict
    
    world_start_pos_x = - (tile_length * grid_dimension[0]) / 2
    world_start_pos_y = - (tile_length * grid_dimension[1]) / 2

    tileoid_length = tile_length / tile_res

    render_center_x, render_center_y, render_center_z = get_tile_from_pos(player_pos[0], player_pos[1], player_pos[2])
    render_radius = int(flashlight_radius / tile_length)
    for x in range(render_center_x - render_radius, render_center_x + render_radius + 1):
        for y in range(render_center_y - render_radius, render_center_y + render_radius + 1):
            for z in range(render_center_z - render_radius, render_center_z + render_radius + 1):
                if (x,y,z) not in tiles_dict:
                    continue

                tile_pos_x, tile_pos_y, tile_pos_z = (x,y,z)
                tile_info_dict = tiles_dict[(x,y,z)]

                tile_start_x = world_start_pos_x + tile_pos_x * tile_length
                tile_end_x = tile_start_x + tile_length

                tile_start_y = world_start_pos_y + tile_pos_y * tile_length
                tile_end_y = tile_start_y + tile_length

                tile_start_z = tile_pos_z * tile_length
                tile_end_z = tile_start_z + tile_length

                cur_y = tile_start_y

                while cur_y < tile_end_y:
                    cur_x = tile_start_x

                    while cur_x < tile_end_x:
                        cur_z = tile_start_z

                        while cur_z < tile_end_z:

                            if should_objected_be_rendered((cur_x + tileoid_length/2, cur_y + tileoid_length/2, cur_z + tileoid_length/2)):
                                tileoid_color_r, tileoid_color_g, tileoid_color_b = get_adjusted_object_color((cur_x + tileoid_length/2, cur_y + tileoid_length/2, cur_z + tileoid_length/2), tile_info_dict['color'])
                                glPushMatrix()
                                glColor3f(tileoid_color_r, tileoid_color_g , tileoid_color_b)
                                glTranslatef(cur_x + tileoid_length / 2, cur_y + tileoid_length/2, cur_z + tileoid_length/2)
                                glScale(tileoid_length, tileoid_length, tileoid_length)
                                glutSolidCube(1)
                                glPopMatrix()

                            cur_z += tileoid_length
                        cur_x += tileoid_length
                    cur_y += tileoid_length

def drawPlayer():
    player_x, player_y, player_z = player_pos
    glPushMatrix()
    glColor3f(1, 0, 0)
    glTranslatef(player_x, player_y, player_z)
    glRotatef(player_angle, 0, 0, 1)
    
    glutSolidCube(20)
    glPopMatrix()
    
def handlePlayerMovement():
    global movement_keys_pressed, player_acceleration, player_forward_velocity_multiplier, player_sideward_velocity_multiplier
    global player_pos, world_ground_level, player_upward_velocity_multiplier

    player_movement_vector_x, player_movement_vector_y = get_player_forward_vector()

    key_pressed = False

    if movement_keys_pressed['w']:
        key_pressed = True
        player_forward_velocity_multiplier = min(player_forward_velocity_multiplier + player_acceleration * delta_time, 1)


    if movement_keys_pressed['s']:
        key_pressed = True
        player_forward_velocity_multiplier = max(player_forward_velocity_multiplier - player_acceleration * delta_time, -1)

    if movement_keys_pressed['a']:
        key_pressed = True
        player_sideward_velocity_multiplier = min(player_sideward_velocity_multiplier + player_acceleration * delta_time, 1)

    if movement_keys_pressed['d']:
        key_pressed = True
        player_sideward_velocity_multiplier = max(player_sideward_velocity_multiplier - player_acceleration * delta_time, -1)

    if movement_keys_pressed['space'] and is_player_grounded():
        player_upward_velocity_multiplier = player_jump_force
    #deceleraton
    if not key_pressed:

        if player_forward_velocity_multiplier < 0:
            player_forward_velocity_multiplier += player_acceleration * delta_time
            if player_forward_velocity_multiplier > 0: 
                player_forward_velocity_multiplier = 0

        elif player_forward_velocity_multiplier > 0:
            player_forward_velocity_multiplier -= player_acceleration * delta_time
            if player_forward_velocity_multiplier < 0:
                player_forward_velocity_multiplier = 0

        if player_sideward_velocity_multiplier < 0:
            player_sideward_velocity_multiplier += player_acceleration * delta_time
            if player_sideward_velocity_multiplier > 0: 
                player_sideward_velocity_multiplier = 0

        elif player_sideward_velocity_multiplier > 0:
            player_sideward_velocity_multiplier -= player_acceleration * delta_time
            if player_sideward_velocity_multiplier < 0:
                player_sideward_velocity_multiplier = 0

    #forward_movement
    movement_vector_x = player_normal_movement_velocity * player_movement_vector_x * delta_time * player_forward_velocity_multiplier
    movement_vector_y = player_normal_movement_velocity * player_movement_vector_y * delta_time * player_forward_velocity_multiplier
    movement_vector_z = 0
    move_player(movement_vector_x, movement_vector_y, movement_vector_z)

    
    #sideways_movement
    left_movement_vector_x = - player_movement_vector_y * player_normal_movement_velocity * delta_time * player_sideward_velocity_multiplier
    left_movement_vector_y = player_movement_vector_x * player_normal_movement_velocity * delta_time * player_sideward_velocity_multiplier
    move_player(left_movement_vector_x, left_movement_vector_y , 0)

    #gravity
    if not is_player_grounded():
        player_upward_velocity_multiplier -= player_gravity * delta_time
        if player_pos[2] - player_height < world_ground_level:
            player_pos[2] = world_ground_level + player_height

    if is_player_grounded() and player_upward_velocity_multiplier < 0:
        player_upward_velocity_multiplier = 0

    move_player(0, 0, 9 * player_upward_velocity_multiplier * delta_time)

def get_crosshair_target():
    aim_x, aim_y, aim_z = get_player_aim_vector()

    ray_origin_x, ray_origin_y, ray_origin_z = weapon_bullet_ray_origin_pos
    aim_distance = 500

    current_x = ray_origin_x
    current_y = ray_origin_y
    current_z = ray_origin_z

    step_length = 1

    for i in range(int(aim_distance / step_length)):

        current_x += aim_x * step_length
        current_y += aim_y * step_length
        current_z += aim_z * step_length

        
        tile_x, tile_y, tile_z = get_tile_from_pos(current_x, current_y, current_z)
        if is_tile_occupied(tile_x, tile_y, tile_z):
            return (current_x, current_y, current_z)

        
        for drone in drones:
            drone_x, drone_y, drone_z = drone['current_real_pos']
            drone_radius = drone['length'] / 2

            distance_to_drone_squared = get_distance_squared((current_x, current_y, current_z), (drone_x, drone_y, drone_z))
            if distance_to_drone_squared <= drone_radius ** 2:
                return (current_x, current_y, current_z)

        #main enemy collision
        enemy_x, enemy_y, enemy_z = main_enemy_info['real_pos']
        enemy_radius = (main_enemy_info['length'] * tile_length) / 2

        distance_to_enemy_squared = get_distance_squared((current_x, current_y, current_z), (enemy_x, enemy_y, enemy_z))
        if distance_to_enemy_squared <= enemy_radius ** 2:
            return (current_x, current_y, current_z)

    
    target_x = ray_origin_x + aim_x * aim_distance
    target_y = ray_origin_y + aim_y * aim_distance
    target_z = ray_origin_z + aim_z * aim_distance

    return (target_x, target_y, target_z)


def shoot_bullet():
    global bullet_left
    if bullet_left <= 0:
        return
    global bullets
    muzzle_x, muzzle_y, muzzle_z = weapon_bullet_ray_origin_pos

    direction_x, direction_y, direction_z = get_player_aim_vector()
    global last_bullet_shoot_time
    cooldown_time = 4
    cur_time = time.time()
    if  last_bullet_shoot_time == None or  (cur_time - last_bullet_shoot_time) > cooldown_time:
        bullet = {'pos': [muzzle_x, muzzle_y, muzzle_z], 'direction': [direction_x, direction_y, direction_z], 'speed' : 10, 'damage': 10}
        bullets.append(bullet)
        bullet_left -= 1
        last_bullet_shoot_time = cur_time

def check_bullet_collisions():
    global bullets

    new_bullets_list = []

    world_min_x = -(tile_length * grid_dimension[0]) / 2
    world_max_x = world_min_x + tile_length * grid_dimension[0]

    world_min_y = -(tile_length * grid_dimension[1]) / 2
    world_max_y = world_min_y + tile_length * grid_dimension[1]

    world_min_z = world_ground_level
    world_max_z = 30 * tile_length

    for bullet in bullets:
        bullet_x, bullet_y, bullet_z = bullet['pos']

        #world boundary collision
        if bullet_x < world_min_x or bullet_x > world_max_x:
            continue
        if bullet_y < world_min_y or bullet_y > world_max_y:
            continue
        if bullet_z < world_min_z or bullet_z > world_max_z:
            continue


        #tile collision
        tile_x, tile_y, tile_z = get_tile_from_pos(bullet_x, bullet_y, bullet_z)
        if is_tile_occupied(tile_x, tile_y, tile_z):
            continue

        colliding = False
        #drone collision
        for drone in drones:
            drone_x, drone_y, drone_z = drone['current_real_pos']
            drone_radius = drone['length']

            distance_to_drone_squared = get_distance_squared((bullet_x, bullet_y, bullet_z), (drone_x, drone_y, drone_z))
            if distance_to_drone_squared <= drone_radius ** 2:
                colliding = True
                drone['health'] -= (bullet['damage']) / drone_collision_sphere_multiplier
                # print('drone collide with bullete')
                break

        #main enemy collision
        if not colliding:
            enemy_x, enemy_y, enemy_z = main_enemy_info['real_pos']
            enemy_radius = (main_enemy_info['length'] * tile_length) / 2

            distance_to_enemy_squared = get_distance_squared((bullet_x, bullet_y, bullet_z), (enemy_x, enemy_y, enemy_z))
            if distance_to_enemy_squared <= enemy_radius ** 2:
                colliding = True
                main_enemy_info['health'] -= bullet['damage']

        if not colliding:
            new_bullets_list.append(bullet)

    bullets = new_bullets_list

def move_bullets():

    global bullets
    for bullet in bullets:

        bullet['pos'][0] += bullet['direction'][0] * bullet['speed'] * delta_time * 100
        bullet['pos'][1] += bullet['direction'][1] * bullet['speed'] * delta_time * 100
        bullet['pos'][2] += bullet['direction'][2] * bullet['speed'] * delta_time * 100

def render_bullets():

    for bullet in bullets:
        x, y, z = bullet['pos']
        if (player_pos[0] - player_width /2 <= x <= player_pos[0] + player_width /2
            or player_pos[1] - player_width /2 <= x <= player_pos[1] + player_width /2
        ):
            continue
        if should_illuminated_objected_be_rendered((x,y,z)):
            cr, cg, cb = get_adjusted_illuminated_object_color((x,y,z), (1,1,0))
            glPushMatrix()
            glColor3f(cr, cg, cb)
            glTranslatef(x, y, z)
            glutSolidSphere(1, 10, 10)
            glPopMatrix()

def is_player_in_detection_range_of_drone(drone):

    drone_tile_x, drone_tile_y, drone_tile_z = drone['tile_pos']
    player_tile_x, player_tile_y, player_tile_z = get_tile_from_pos(player_pos[0], player_pos[1], player_pos[2])

    distance_squared = get_distance_squared(
        (drone_tile_x, drone_tile_y, drone_tile_z),
        (player_tile_x, player_tile_y, player_tile_z)
    )

    return distance_squared <= drone['detection_range'] ** 2

def do_drone_have_line_of_sight_of_player(drone_pos, player_pos):

    direction_vector_x = player_pos[0] - drone_pos[0]
    direction_vector_y = player_pos[1] - drone_pos[1]
    direction_vector_z = player_pos[2] - drone_pos[2]

    direction_distance = (direction_vector_x ** 2 + direction_vector_y ** 2 + direction_vector_z ** 2) ** (1/2)

    if direction_distance == 0: return True

    dx = direction_vector_x / direction_distance
    dy = direction_vector_y / direction_distance
    dz = direction_vector_z / direction_distance

    current_tile_x = drone_pos[0]
    current_tile_y = drone_pos[1]
    current_tile_z = drone_pos[2]


    for i in range(math.ceil(direction_distance + 1)):

        current_tile_x += dx
        current_tile_y += dy
        current_tile_z += dz

        if is_tile_occupied(round(current_tile_x), round(current_tile_y), round(current_tile_z)):
            return False

    return True

def can_drone_see_player(drone):

    if total_drone_follwing_player >= max_drone_that_can_follow:
        return False

    if not is_player_in_detection_range_of_drone(drone):
        return False

    drone_pos = drone['tile_pos']
    player_tile_x, player_tile_y, player_tile_z = get_tile_from_pos(player_pos[0], player_pos[1], player_pos[2])

    return do_drone_have_line_of_sight_of_player(drone_pos, (player_tile_x, player_tile_y, player_tile_z))

def calculate_drones_next_tile():
    global drones, main_enemy_info

    total_path_finding_robots = 0

    for drone in drones:
        if drone['next_tile_pos'] != None:
            continue

        if can_drone_see_player(drone):

            if total_path_finding_robots >= max_drone_that_can_follow:
                continue
            total_path_finding_robots += 1

            player_tile_x, player_tile_y, player_tile_z = get_tile_from_pos(player_pos[0], player_pos[1], player_pos[2])
            drone['last_seen_tile'] = [player_tile_x, player_tile_y, drone['tile_pos'][2]]

            main_enemy_info['target_tile'] = [player_tile_x, player_tile_y, player_tile_z]

            path_list = calculate_drone_path(drone['tile_pos'], drone['last_seen_tile'])
            if len(path_list) < 2:
                continue
            next_best_tile = path_list[1]
            drone['next_tile_pos'] = list(next_best_tile)

        elif drone['last_seen_tile'] != None:

            if total_path_finding_robots >= max_drone_that_can_follow:
                continue
            total_path_finding_robots += 1

            path_list = calculate_drone_path(drone['tile_pos'], drone['last_seen_tile'])
            if len(path_list) < 2:
                continue
            next_best_tile = path_list[1]            
            drone['next_tile_pos'] = list(next_best_tile)



def move_drones():
    global drones, total_drone_follwing_player
    total_drone_follwing_player = 0
    for drone in drones:
        if drone['next_tile_pos'] != None: #move

            total_drone_follwing_player += 1

            before_pos = drone['current_real_pos']
            next_tile_x, next_tile_y, next_tile_z = drone['next_tile_pos']
            after_pos = get_world_pos_from_tile(next_tile_x, next_tile_y, next_tile_z)
        
            direction_x = after_pos[0] - before_pos[0]
            direction_y = after_pos[1] - before_pos[1]
            direction_z = after_pos[2] - before_pos[2]
        
            distance = (direction_x ** 2 + direction_y ** 2 + direction_z ** 2) ** 0.5
        
            if distance < drone['speed'] * delta_time:
                drone['tile_pos'] = drone['next_tile_pos']
                drone['next_tile_pos'] = None
                drone_x, drone_y, drone_z = drone['tile_pos']
                drone['current_real_pos'] = get_world_pos_from_tile(drone_x, drone_y, drone_z)
                continue
        
            dx = direction_x / distance
            dy = direction_y / distance
            dz = direction_z / distance
        
            drone['current_real_pos'][0] += dx * drone['speed'] * delta_time
            drone['current_real_pos'][1] += dy * drone['speed'] * delta_time
            drone['current_real_pos'][2] += dz * drone['speed'] * delta_time
                

def draw_drone(tile_x, tile_y, tile_z, color, length, detection_range, speed, health):
    drone = {
        'tile_pos': [tile_x, tile_y, tile_z],
        'color' : color,
        'length' : length,
        'detection_range': detection_range,
        'speed' : speed,
        'last_seen_tile' : None,
        'current_real_pos' : get_world_pos_from_tile(tile_x, tile_y, tile_z),
        'next_tile_pos' : None,
        'health' : health
    }

    drones.append(drone)

def calculate_drone_path(start, goal):
    global grid_dimension

    start = tuple(start)
    goal = tuple(goal)

    def heuristic(node):
        return abs(node[0] - goal[0]) + abs(node[1] - goal[1]) + abs(node[2] - goal[2])

    max_x, max_y = grid_dimension[0], grid_dimension[1]
    max_z = 30

    fringe = []
    
    start_g = 0
    start_f = start_g + heuristic(start)
    
    heapq.heappush(fringe, (start_f, start_g, start))

    g_scores = {tuple(start): 0}
    
    came_from = {}

    neighbors_offsets = [
        (1, 0, 0), (-1, 0, 0),
        (0, 1, 0), (0, -1, 0),
        (0, 0, 1), (0, 0, -1)
    ]

    while fringe:
        f_n, g_n, current = heapq.heappop(fringe)

        if current == goal:
            path = []
            curr = goal
            while tuple(curr) in came_from:
                path.append(curr)
                curr = came_from[tuple(curr)]
            path.append(start)
            return path[::-1]

        if g_n > g_scores.get(tuple(current), float('inf')):
            continue

        for dx, dy, dz in neighbors_offsets:
            nx, ny, nz = current[0] + dx, current[1] + dy, current[2] + dz
            neighbor = (nx, ny, nz)

            if not (0 <= nx <= max_x and 0 <= ny <= max_y and 0 <= nz <= max_z):
                continue

            if is_tile_occupied(nx, ny, nz):
                continue

            tentative_g = g_n + 1

            if tentative_g < g_scores.get(tuple(neighbor), float('inf')):
                came_from[tuple(neighbor)] = current
                g_scores[tuple(neighbor)] = tentative_g
                
                f_neighbor = tentative_g + heuristic(neighbor)
                heapq.heappush(fringe, (f_neighbor, tentative_g, neighbor))

    return []


def render_drones():

    def draw_wing_triangle(size, mirror=False):
        """Draws a flat right-angle triangle in the XY plane (parallel to the ground).
        Right angle sits at the sphere's surface (origin), extending outward along X
        and sideways along Y. Set mirror=True for the opposite-side wing."""
        x_dir = -1.0 if mirror else 1.0

        glBegin(GL_TRIANGLES)
        glNormal3f(0.0, 0.0, 1.0)
        glVertex3f(0.0, 0.0, 0.0)                  # right-angle corner (at sphere)
        glVertex3f(x_dir * size, 0.0, 0.0)         # tip, out to the side
        glVertex3f(0.0, size, 0.0)                 # tip, sideways
        glEnd()

    world_start_pos_x = -(tile_length * grid_dimension[0]) / 2
    world_start_pos_y = -(tile_length * grid_dimension[1]) / 2

    for drone in drones:

        x,y,z = drone['current_real_pos']

        if should_objected_be_rendered((x,y,z)):

            drone_adjusted_color = get_adjusted_object_color((x,y,z), drone['color'])
            glPushMatrix()

            glColor3f(drone_adjusted_color[0], drone_adjusted_color[1], drone_adjusted_color[2] )
            glTranslatef(x, y, z)
            glutSolidSphere(drone['length'], 32, 32)

            wing_size = drone['length'] * 3
            draw_wing_triangle(wing_size, mirror=False)   # right wing
            draw_wing_triangle(wing_size, mirror=True)    # left wing

            glPopMatrix()

def draw_main_enemy(tile_x, tile_y, tile_z, length, health, speed, color, damage_rate):
    global main_enemy_info
    if length % 2 == 1: length += 1
    main_enemy_info['real_pos'] = get_world_pos_from_tile(tile_x, tile_y, tile_z)
    main_enemy_info['length'] = length
    main_enemy_info['health'] = health
    main_enemy_info['color'] = color
    main_enemy_info['speed'] = speed
    main_enemy_info['target_tile'] = None
    main_enemy_info['damage'] = damage_rate

def move_main_enemy():
    global main_enemy_info
    if main_enemy_info['target_tile'] == None: return

    enemy_x, enemy_y, enemy_z = main_enemy_info['real_pos']
    target_x, target_y, target_z = main_enemy_info['target_tile']
    target_x, target_y, target_z = get_world_pos_from_tile(target_x, target_y, target_z)


    direction_vector_x = target_x - enemy_x
    direction_vector_y = target_y - enemy_y

    direction_vector_length = (direction_vector_x ** 2 + direction_vector_y ** 2) ** 0.5
    dx = direction_vector_x / direction_vector_length
    dy = direction_vector_y / direction_vector_length



    main_enemy_info['real_pos'][0] += dx * delta_time * main_enemy_info['speed']
    main_enemy_info['real_pos'][1] += dy * delta_time * main_enemy_info['speed']

def destroy_tiles_occupied_by_main_enemy():

    global tiles_dict

    x, y, z = main_enemy_info['real_pos']
    tile_x, tile_y, tile_z = get_tile_from_pos(x,y,z)

    length = main_enemy_info['length']

    half_length = length // 2

    for x in range(tile_x - half_length, tile_x + half_length + 1):
        for y in range(tile_y - half_length, tile_y + half_length + 1):
            for z in range(tile_z - half_length, tile_z + half_length + 1):

                tile = (x, y, z)
                if tile in tiles_dict:
                    
                    del tiles_dict[tile]

def check_player_collision_with_main_enemy():
    global health

    enemy_x, enemy_y, enemy_z = main_enemy_info['real_pos']
    enemy_radius = (main_enemy_info['length'] * tile_length) / 2

    distance_to_enemy_squared = get_distance_squared(player_pos, (enemy_x, enemy_y, enemy_z))

    if distance_to_enemy_squared <= enemy_radius ** 2:
        health -= main_enemy_info['damage'] * delta_time

def render_main_enemy():
    global main_enemy_info
    enemy_x, enemy_y, enemy_z = main_enemy_info['real_pos']
    if should_illuminated_objected_be_rendered((enemy_x, enemy_y, enemy_z)):
        enemy_cr, enemy_cg, enemy_cb = get_adjusted_illuminated_object_color((enemy_x, enemy_y, enemy_z), main_enemy_info['color'])
        

        glPushMatrix()

        glColor3f(enemy_cr, enemy_cg, enemy_cb)

        glTranslatef(enemy_x, enemy_y, enemy_z)

        glutSolidSphere((main_enemy_info['length'] * tile_length/2),32,32)

        glPopMatrix()

def check_enemies_health():
    global drones, main_enemy_info

    new_drones_list = []

    for drone in drones:
        if drone['health'] > 0:
            new_drones_list.append(drone)
        
    drones = new_drones_list

    
    if main_enemy_info['health'] <= 0:
        pass

def check_should_game_be_over():
    global bullet_left, game_state, health
    if bullet_left <= 0:
        game_state = 'over'
    if health <= 0:
        game_state = 'over'

def check_should_game_be_won():
    global main_enemy_info, game_state
    if main_enemy_info['health'] <= 0:
        game_state = 'won'
    

def reset_game(should_load_randomised_map = False):
    global player_pos, player_angle, health, game_state, bullet_left
    global player_forward_velocity_multiplier, player_sideward_velocity_multiplier, player_upward_velocity_multiplier
    global movement_keys_pressed, camera_pitch, total_drone_follwing_player
    global tiles_dict, drones, bullets, cursor_locked, is_minimap_visible

    player_pos = [0,100,200]
    player_angle = 0
    health = 100

    game_state = 'running'
    bullet_left = 40

    player_forward_velocity_multiplier = 0.0
    player_sideward_velocity_multiplier = 0.0
    player_upward_velocity_multiplier = 0.0

    movement_keys_pressed = {'w': False, 's': False, 'a': False, 'd': False, 'space': False}

    camera_pitch = 0
    total_drone_follwing_player = 0

    is_minimap_visible = False

    cursor_locked = True

    tiles_dict = {}
    drones = []
    bullets = []

    if should_load_randomised_map:
        load_randomised_map()
    else:
        loadMap()
        

def keyboardListener(key, x, y):
    """
    Handles keyboard inputs for player movement, gun rotation, camera updates, and cheat mode toggles.
    """
    global player_pos, camera_mode, cursor_locked, movement_keys_pressed
    global game_state



    if key == b'\x1b':  # ESC
        cursor_locked = not cursor_locked
        if not cursor_locked:
            glutSetCursor(GLUT_CURSOR_LEFT_ARROW)
        else:
            glutSetCursor(GLUT_CURSOR_NONE)
            glutWarpPointer(mouse_center_x, mouse_center_y)

        if game_state == 'running':
            game_state = 'paused'
        elif game_state == 'paused':
            game_state = 'running'

    if key == b'w':
        movement_keys_pressed['w'] = True
    if key == b's':
        movement_keys_pressed['s'] = True
    if key == b'a':
        movement_keys_pressed['a'] = True
    if key == b'd':
        movement_keys_pressed['d'] = True

    if key == b' ':
        movement_keys_pressed['space'] = True
    # # Toggle cheat mode (C key)
    # if key == b'c':

    if key == b'v':
        if camera_mode == 'tps':
            camera_mode = 'fps'
        else: 
            camera_mode = 'tps'

    # # Reset the game if R key is pressed
    if key == b'r':
        reset_game()

    if key == b'k':
        reset_game(True)

    global is_minimap_visible

    if key == b'm':
        is_minimap_visible = not is_minimap_visible

def keyboardUpListener(key, x, y):
    if key == b'w':
        movement_keys_pressed['w'] = False

    if key == b's':
        movement_keys_pressed['s'] = False

    if key == b'a':
        movement_keys_pressed['a'] = False

    if key == b'd':
        movement_keys_pressed['d'] = False
    if key == b' ':
        movement_keys_pressed['space'] = False

def mouseMotionListener(x, y):
    global camera_pitch, player_angle
    global last_mouse_x, last_mouse_y
    global mouse_sensitivity

    dy = y - mouse_center_y
    dx = x - mouse_center_x

    if not delta_time == None and cursor_locked: 
        camera_pitch -= dy * mouse_sensitivity * 0.5 * (delta_time * 10)
        player_angle -= dx * mouse_sensitivity * (delta_time * 17)


    if camera_pitch < -60:
        camera_pitch = -60
    elif camera_pitch > 60:
        camera_pitch = 60

    if cursor_locked:
        glutWarpPointer(mouse_center_x, mouse_center_y)
        

def specialKeyListener(key, x, y):
    """
    Handles special key inputs (arrow keys) for adjusting the camera angle and height.
    """
    # Move camera up (UP arrow key)
    # if key == GLUT_KEY_UP:

    # # Move camera down (DOWN arrow key)
    # if key == GLUT_KEY_DOWN:

    # moving camera left (LEFT arrow key)
    if key == GLUT_KEY_LEFT:
        pass

    # moving camera right (RIGHT arrow key)
    if key == GLUT_KEY_RIGHT:
        pass

def mouseListener(button, state, x, y):
    """
    Handles mouse inputs for firing bullets (left click) and toggling camera mode (right click).
    """
    #Left mouse button fires a bullet
    if button == GLUT_LEFT_BUTTON and state == GLUT_DOWN:
        shoot_bullet()

        # # Right mouse button toggles camera tracking mode
        # if button == GLUT_RIGHT_BUTTON and state == GLUT_DOWN:


def setupCamera():
    """
    Configures the camera's projection and view settings.
    Uses a perspective projection and positions the camera to look at the target.
    """
    global weapon_bullet_ray_origin_pos

    glMatrixMode(GL_PROJECTION)  # Switch to projection matrix mode
    glLoadIdentity()  # Reset the projection matrix
    # Set up a perspective projection (field of view, aspect ratio, near clip, far clip)
    gluPerspective(fovY, window_width/ window_height, 0.1, 1500) # Think why aspect ration is 1.25?
    glMatrixMode(GL_MODELVIEW)  # Switch to model-view matrix mode
    glLoadIdentity()  # Reset the model-view matrix

    player_x, player_y, player_z = player_pos
    player_forward_vector_x ,player_forward_vector_y = get_player_forward_vector()
    player_aim_vector_x, player_aim_vector_y, player_aim_vector_z = get_player_aim_vector() 
    if camera_mode == 'fps':
        camera_pos_offset = 0
        camera_lookAt_offset = 200
        camera_pos_x = player_x + camera_pos_offset * player_forward_vector_x
        camera_pos_y = player_y + camera_pos_offset * player_forward_vector_y
        camera_pos_z = player_z + 50
        weapon_bullet_ray_origin_pos = [camera_pos_x, camera_pos_y, camera_pos_z]

    if camera_mode == 'tps':
        camera_pos_offset = - 75
        camera_lookAt_offset = 200
        camera_pos_x = player_x + camera_pos_offset * player_forward_vector_x
        camera_pos_y = player_y + camera_pos_offset * player_forward_vector_y
        camera_pos_z = player_z + 70
        weapon_bullet_ray_origin_pos = [camera_pos_x, camera_pos_y, camera_pos_z]

    camera_look_at_x = player_x + camera_lookAt_offset * player_aim_vector_x
    camera_look_at_y = player_y + camera_lookAt_offset * player_aim_vector_y
    camera_look_at_z = player_z + 50 + camera_lookAt_offset * player_aim_vector_z
    # Position the camera and set its orientation
    gluLookAt(camera_pos_x, camera_pos_y , camera_pos_z,  # Camera position
              camera_look_at_x, camera_look_at_y, camera_look_at_z,  # Look-at target
              0, 0, 1)  # Up vector (z-axis)


def updateWeaponMuzzlePosition():
    global player_pos, weapon_muzzle_pos, weapon_length, weapon_side_offset

    player_forward_x, player_forward_y = get_player_forward_vector()
    player_aim_x, player_aim_y, player_aim_z = get_player_aim_vector()

    muzzle_x = player_pos[0] + player_aim_x * weapon_length
    muzzle_y = player_pos[1] + player_aim_y * weapon_length
    muzzle_z = player_pos[2] - player_height / 2 + player_aim_z * weapon_length

    player_perpendicular_x = player_forward_y
    player_perpendicular_y = - player_forward_x
    muzzle_x += player_perpendicular_x * weapon_side_offset
    muzzle_y += player_perpendicular_y * weapon_side_offset

    weapon_muzzle_pos = [muzzle_x, muzzle_y, muzzle_z]

def idle():
    """
    Idle function that runs continuously:
    - Triggers screen redraw for real-time updates.
    """
    global current_time, delta_time, game_state
    new_time = time.time()
    delta_time = new_time - current_time
    current_time = new_time

    if game_state == 'running':

        destroy_tiles_occupied_by_main_enemy()
        handlePlayerMovement()
        updateWeaponMuzzlePosition()
        move_bullets()
        calculate_drones_next_tile()
        move_drones()
        check_bullet_collisions()
        move_main_enemy()
        check_player_collision_with_main_enemy()
        check_enemies_health()

        check_should_game_be_over()
        check_should_game_be_won()
    # Ensure the screen updates with the latest changes
    glutPostRedisplay()


def showScreen():
    """
    Display function to render the game scene:
    - Clears the screen and sets up the camera.
    - Draws everything of the screen
    """
    # Clear color and depth buffers
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    glLoadIdentity()  # Reset modelview matrix
    glViewport(0, 0, window_width, window_height)  # Set viewport size

    setupCamera()  # Configure camera perspective

    render_tiles()
    drawPlayer()
    render_bullets()
    render_drones()
    render_main_enemy()

    # Display game info text at a fixed screen position
    if game_state == 'running':
        draw_text(15, 115, f"Main enemy health: {main_enemy_info['health']}")
        draw_text(15, 80, f"Bullet left: {bullet_left}")
        draw_text(15, 45, f"Health: {round(health)}")
        draw_text(15, 10, f"How many drones are following me?: {total_drone_follwing_player}")
        drawCrosshair()
    elif game_state == 'paused':
        draw_text(window_width/2 - window_width/15, window_height/2 + 35, "Game is paused.")
        draw_text(window_width/2 - window_width/15, window_height/2, "Press escape to resume!")
        draw_text(window_width/2 - window_width/15, window_height/2 - 35, "Press R to restart!")
    elif game_state == 'over':
        draw_text(window_width/2 - window_width/15, window_height/2 + 15, "GAME OVER!.")
        draw_text(window_width/2 - window_width/15, window_height/2 - 20, "Press R to restart!")
        draw_text(window_width/2 - window_width/15, window_height/2 - 55, "Press k to restart in a random map!")


    elif game_state == 'won':
        draw_text(window_width/2 - window_width/10, window_height/2 + 15, "CONGRATS! You have won the game!.")
        draw_text(window_width/2 - window_width/15, window_height/2 - 20, "Press R to restart!")
        draw_text(window_width/2 - window_width/15, window_height/2 - 55, "Press K restart in a random map!")

    if is_minimap_visible:
        draw_minimap()

    # Swap buffers for smooth rendering (double buffering)
    glutSwapBuffers()



def loadMap():
    draw_floor()
    draw_wall(20,90,0,50,4, 15, {'color': (0,0,1)})
    draw_wall(40,42,0,55,4, 8, {'color': (0,1,0)})
    draw_wall(5,5,0,5,2, 15, {'color': (1,0,0)})
    draw_wall(10,50,0,2,25, 15, {'color': (0,1,0)})
    draw_wall(55,70,0,25,10, 15, {'color': (0,1,0)})
    

    draw_main_enemy(0, 100, 8, 14, 100, 70, (1,1,0), 100)

    draw_drone(10, 10, 11, (0, 0, 1), 10, 20, 40, 50)
    draw_drone(25, 10, 11, (0, 0, 1), 10, 20, 40, 50)
    draw_drone(40, 10, 13, (0, 0, 1), 10, 20, 40, 50)

    draw_drone(10, 25, 11, (0, 0, 1), 10, 20, 40, 50)
    draw_drone(25, 25, 11, (0, 0, 1), 10, 20, 40, 50)
    draw_drone(40, 25, 11, (0, 0, 1), 10, 20, 40, 50)
    
def load_randomised_map():
    """
    Randomized level. Each of the four 40x50 quadrants gets a handful
    of randomly sized/placed rooms, built with the same draw_wall()
    used by loadMap(). The 20x50 middle strip stays clear so the
    main enemy has room to move. Main enemy and drone spawn tiles are
    randomized too, kept clear of walls and away from the player.
    The player spawns near one of the four map corners, also clear of walls.
    """

    draw_floor()

    zone_margin = 3
    wall_gap = 2
    min_wall_size = 4
    max_wall_size = 10
    max_structures_per_zone = 4

    middle_zone = {
        'x_min': 40, 'x_max': 60,
        'y_min': 25, 'y_max': 75
    }

    zones = {
        'top_left':     {'x_min': 0,  'x_max': 40,  'y_min': 50, 'y_max': 100},
        'top_right':    {'x_min': 60, 'x_max': 100, 'y_min': 50, 'y_max': 100},
        'bottom_left':  {'x_min': 0,  'x_max': 40,  'y_min': 0,  'y_max': 50},
        'bottom_right': {'x_min': 60, 'x_max': 100, 'y_min': 0,  'y_max': 50}
    }

    placed_structures = []

    def footprint_is_inside_zone(x, y, width, length, zone):
        min_x = zone['x_min'] + zone_margin
        max_x = zone['x_max'] - zone_margin
        min_y = zone['y_min'] + zone_margin
        max_y = zone['y_max'] - zone_margin

        if x < min_x or x + width > max_x:
            return False
        if y < min_y or y + length > max_y:
            return False

        if (x < middle_zone['x_max'] and x + width > middle_zone['x_min']
                and y < middle_zone['y_max'] and y + length > middle_zone['y_min']):
            return False

        return True

    def footprint_has_required_gap(x, y, width, length):
        for (old_x_min, old_x_max, old_y_min, old_y_max) in placed_structures:
            if (x - wall_gap < old_x_max and x + width + wall_gap > old_x_min
                    and y - wall_gap < old_y_max and y + length + wall_gap > old_y_min):
                return False
        return True

    for zone_name, zone in zones.items():

        structure_count = random.randint(1, max_structures_per_zone)

        for _ in range(structure_count):
            for attempt in range(150):

                width = random.randint(min_wall_size, max_wall_size)
                length = random.randint(min_wall_size, max_wall_size)

                start_x = random.randint(zone['x_min'], zone['x_max'] - width)
                start_y = random.randint(zone['y_min'], zone['y_max'] - length)

                if not footprint_is_inside_zone(start_x, start_y, width, length, zone):
                    continue

                if not footprint_has_required_gap(start_x, start_y, width, length):
                    continue

                draw_wall(
                    start_x, start_y, 0,
                    width, length, 15,
                    {'color': (0, 1, 0)}
                )

                placed_structures.append((
                    start_x, start_x + width,
                    start_y, start_y + length
                ))

                break

    def tile_is_inside_any_structure(x, y):
        for (old_x_min, old_x_max, old_y_min, old_y_max) in placed_structures:
            if old_x_min - wall_gap <= x <= old_x_max + wall_gap and old_y_min - wall_gap <= y <= old_y_max + wall_gap:
                return True
        return False

    #pick a random corner-ish tile for the player, avoiding walls
    corner_margin = 8

    corner_candidates = {
        'bottom_left':  (0 + corner_margin, 0 + corner_margin),
        'bottom_right': (grid_dimension[0] - corner_margin, 0 + corner_margin),
        'top_left':     (0 + corner_margin, grid_dimension[1] - corner_margin),
        'top_right':    (grid_dimension[0] - corner_margin, grid_dimension[1] - corner_margin)
    }

    def find_valid_player_tile(base_x, base_y):
        for attempt in range(200):
            x = base_x + random.randint(-corner_margin, corner_margin)
            y = base_y + random.randint(-corner_margin, corner_margin)

            x = max(1, min(grid_dimension[0] - 2, x))
            y = max(1, min(grid_dimension[1] - 2, y))

            if tile_is_inside_any_structure(x, y):
                continue

            return (x, y)

        return (base_x, base_y)

    chosen_corner_name = random.choice(list(corner_candidates.keys()))
    chosen_corner_x, chosen_corner_y = corner_candidates[chosen_corner_name]

    player_tile_x, player_tile_y = find_valid_player_tile(chosen_corner_x, chosen_corner_y)

    player_spawn_world_pos = get_world_pos_from_tile(player_tile_x, player_tile_y, 0)
    player_pos[0] = player_spawn_world_pos[0]
    player_pos[1] = player_spawn_world_pos[1]

    #keep enemies away from walls and away from the player's spawn tile

    player_spawn_tile_x, player_spawn_tile_y, player_spawn_tile_z = get_tile_from_pos(
        player_pos[0], player_pos[1], player_pos[2]
    )

    def get_random_spawn_tile(zone, min_distance_from_player, avoid_structures):
        for attempt in range(200):
            x = random.randint(zone['x_min'] + zone_margin, zone['x_max'] - zone_margin)
            y = random.randint(zone['y_min'] + zone_margin, zone['y_max'] - zone_margin)

            distance_from_player_squared = (x - player_spawn_tile_x) ** 2 + (y - player_spawn_tile_y) ** 2
            if distance_from_player_squared < min_distance_from_player ** 2:
                continue

            if avoid_structures and tile_is_inside_any_structure(x, y):
                continue

            return (x, y)

        #fallback: just use the zone's corner if nothing valid was found
        return (zone['x_min'] + zone_margin, zone['y_min'] + zone_margin)

    main_enemy_tile_x, main_enemy_tile_y = get_random_spawn_tile(middle_zone, 15, False)
    draw_main_enemy(main_enemy_tile_x, main_enemy_tile_y, 8, 14, 100, 70, (1, 1, 0), 100)

    drone_zone_list = list(zones.values())

    for _ in range(12):
        drone_zone = random.choice(drone_zone_list)
        drone_tile_x, drone_tile_y = get_random_spawn_tile(drone_zone, 20, True)
        draw_drone(drone_tile_x, drone_tile_y, 11, (0, 0, 1), 10, 20, 55, 50)

    print("Randomized map generated.")
    print("Total random structures:", len(placed_structures))


# Main function to set up OpenGL window and loop
def main():

    reset_game()

    glutInit()
    glutInitDisplayMode(GLUT_DOUBLE | GLUT_RGB | GLUT_DEPTH)  # Double buffering, RGB color, depth test
    glutInitWindowSize(window_width, window_height)  # Window size
    glutInitWindowPosition(0, 0)  # Window position
    wind = glutCreateWindow(b"3D OpenGL Intro")  # Create the window

    glEnable(GL_DEPTH_TEST)

    global cursor_locked
    cursor_locked = True
    glutWarpPointer(mouse_center_x, mouse_center_y)
    glutSetCursor(GLUT_CURSOR_NONE)



    glutDisplayFunc(showScreen)  # Register display function
    glutKeyboardFunc(keyboardListener)  # Register keyboard listener
    glutKeyboardUpFunc(keyboardUpListener)
    glutSpecialFunc(specialKeyListener)
    glutMouseFunc(mouseListener)
    glutPassiveMotionFunc(mouseMotionListener)
    glutIdleFunc(idle)  # Register the idle function to move the bullet automatically

    glutMainLoop()  # Enter the GLUT main loop

if __name__ == "__main__":
    main()