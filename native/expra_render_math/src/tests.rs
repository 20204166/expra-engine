use super::{
    camera_input, camera_project, project_points, projection_input, viewport_input, visible_mask,
    ITEM_STRIDE,
};

fn camera_values(rotation: f64) -> Vec<f64> {
    vec![0.0, 0.0, 0.0, 0.0, 20.0, 10.0, rotation, -100.0, 100.0]
}

fn viewport_values() -> Vec<f64> {
    vec![0.0, 0.0, 200.0, 100.0]
}

fn item_record(space: f64, x: f64) -> Vec<f64> {
    let mut record = vec![
        space, 1.0, 1.0, x, 0.0, 0.0, 0.0, 1.0, 1.0, 2.0, 2.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0,
    ];
    record.resize(ITEM_STRIDE, 0.0);
    record
}

#[test]
fn world_projection_matches_the_current_camera_axes() {
    let camera =
        camera_input(&camera_values(std::f64::consts::FRAC_PI_2)).expect("valid Camera2D input");
    let viewport = viewport_input(&viewport_values()).expect("valid viewport");

    let projected = camera_project(1.0, 0.0, camera, viewport);

    assert!((projected.0 - 100.0).abs() < 1e-12);
    assert!((projected.1 - 60.0).abs() < 1e-12);
}

#[test]
fn visibility_intersection_keeps_exact_edges_inclusive() {
    let camera = camera_input(&camera_values(0.0)).expect("valid camera");
    let viewport = viewport_input(&viewport_values()).expect("valid viewport");
    let records = [item_record(0.0, 11.0), item_record(0.0, 11.0001)].concat();

    let mask = visible_mask(&records, &[], camera, viewport).expect("valid visibility batch");

    assert_eq!(mask, vec![true, false]);
}

#[test]
fn viewport_anchor_maps_the_top_left_to_viewport_pixels() {
    let camera = camera_input(&camera_values(0.7)).expect("valid camera");
    let viewport = viewport_input(&viewport_values()).expect("valid viewport");
    let mut record = item_record(1.0, 32.0);
    record[4] = 4.0;
    record[15] = 0.0;
    record[16] = 1.0;
    record[17] = 16.0;
    record[18] = -12.0;

    let mask = visible_mask(&record, &[], camera, viewport).expect("valid HUD batch");

    assert_eq!(mask, vec![true]);
}

#[test]
fn malformed_batch_lengths_are_rejected() {
    let camera = camera_input(&camera_values(0.0)).expect("valid camera");
    let viewport = viewport_input(&viewport_values()).expect("valid viewport");

    assert_eq!(
        visible_mask(&[0.0, 1.0], &[], camera, viewport),
        Err("item record buffer length is not a multiple of 21")
    );
}

#[test]
fn a_declared_radius_must_be_positive() {
    let camera = camera_input(&camera_values(0.0)).expect("valid camera");
    let viewport = viewport_input(&viewport_values()).expect("valid viewport");
    let mut record = item_record(0.0, 0.0);
    record[1] = 3.0;
    record[11] = 1.0;

    assert_eq!(
        visible_mask(&record, &[], camera, viewport),
        Err("item dimensions and outline values are invalid")
    );
}

fn projection_camera_values(rotation: f64) -> Vec<f64> {
    vec![-10.0, 5.0, 40.0, 0.0, 0.0, rotation, 800.0, 600.0]
}

#[test]
fn batched_projection_matches_unrotated_camera2d_pixel_order() {
    let camera = projection_input(&projection_camera_values(0.0)).expect("valid projection camera");

    let projected = project_points(&[2.0, 1.0, -10.0, 5.0], camera).expect("valid points");

    assert_eq!(projected, vec![480.0, 160.0, 0.0, 0.0]);
}

#[test]
fn batched_projection_matches_rotated_camera2d_pixel_order() {
    let camera = projection_input(&projection_camera_values(std::f64::consts::FRAC_PI_2))
        .expect("valid projection camera");

    let projected = project_points(&[1.0, 0.0, 0.0, 1.0], camera).expect("valid points");

    assert!((projected[0] - 400.0).abs() < 1e-12);
    assert!((projected[1] - 340.0).abs() < 1e-12);
    assert!((projected[2] - 440.0).abs() < 1e-12);
    assert!((projected[3] - 300.0).abs() < 1e-12);
}

#[test]
fn batched_projection_accepts_empty_batches() {
    let camera = projection_input(&projection_camera_values(0.0)).expect("valid projection camera");

    assert_eq!(project_points(&[], camera), Ok(Vec::new()));
}

#[test]
fn batched_projection_rejects_malformed_or_non_finite_inputs() {
    assert_eq!(
        projection_input(&[0.0; 7]),
        Err("projection camera record must contain 8 finite values")
    );
    assert_eq!(
        projection_input(&[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 800.0, 600.0]),
        Err("projection scale and viewport dimensions must be positive")
    );
    assert_eq!(
        projection_input(&[0.0, 0.0, 1.0, 0.0, 0.0, f64::INFINITY, 800.0, 600.0]),
        Err("projection camera record must contain 8 finite values")
    );

    let camera = projection_input(&projection_camera_values(0.0)).expect("valid projection camera");
    assert_eq!(
        project_points(&[1.0], camera),
        Err("point buffer must contain finite x/y pairs")
    );
    assert_eq!(
        project_points(&[f64::NAN, 0.0], camera),
        Err("point buffer must contain finite x/y pairs")
    );
    assert_eq!(
        project_points(&[f64::MAX, -f64::MAX], camera),
        Err("projected coordinates must be finite")
    );
}
