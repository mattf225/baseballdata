-- Add old_point and new_point columns to mlb_line_movements
-- Tracks the prop line (e.g. 7.5 strikeouts) for each side of a line movement
ALTER TABLE mlb_line_movements ADD COLUMN IF NOT EXISTS old_point FLOAT;
ALTER TABLE mlb_line_movements ADD COLUMN IF NOT EXISTS new_point FLOAT;
