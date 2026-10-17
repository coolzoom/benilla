-- rollback for tiangong
DELETE FROM `map_template` WHERE `entry` = 800;
DELETE FROM `area_template` WHERE `entry` = 4988;
DELETE FROM `game_tele` WHERE `id` = 8800;
