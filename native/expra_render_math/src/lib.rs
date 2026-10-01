//! Faithful batch port of Expra's renderer-neutral visibility math.
//!
//! This crate does not render, load assets, traverse Entities, or own cameras.
//! Python packs the current RenderItem visual poses and actual RenderContext
//! camera/viewport into one batch. The Python reference remains the fallback.

#![cfg_attr(not(feature = "python-extension"), allow(dead_code))]

const ITEM_STRIDE: usize = 21;
const CAMERA_STRIDE: usize = 9;
const VIEWPORT_STRIDE: usize = 4;

const SPACE_WORLD: u8 = 0;
const SPACE_VIEWPORT: u8 = 1;

const KIND_POINT: u8 = 0;
const KIND_CIRCLE: u8 = 3;
const KIND_POLYGON: u8 = 5;
const KIND_LINE: u8 = 6;

#[derive(Clone, Copy, Debug)]
struct CameraInput {
    position_x: f64,
    position_y: f64,
    offset_x: f64,
    offset_y: f64,
    width: f64,
    height: f64,
    rotation: f64,
    near: f64,
    far: f64,
}

#[derive(Clone, Copy, Debug)]
struct ViewportInput {
    x: f64,
    y: f64,
    width: f64,
    height: f64,
}

#[derive(Clone, Copy, Debug)]
struct ItemInput {
    space: u8,
    kind: u8,
    visible: bool,
    x: f64,
    y: f64,
    z: f64,
    rotation: f64,
    scale_x: f64,
    scale_y: f64,
    width: f64,
    height: f64,
    radius: Option<f64>,
    thickness: f64,
    outline_width: f64,
    anchor_x: f64,
    anchor_y: f64,
    offset_x: f64,
    offset_y: f64,
    point_start: usize,
    point_count: usize,
}

fn finite(values: &[f64]) -> bool {
    values.iter().all(|value| value.is_finite())
}

fn item_input(record: &[f64]) -> Result<ItemInput, &'static str> {
    if record.len() != ITEM_STRIDE || !finite(record) {
        return Err("item record must contain 21 finite values");
    }
    let space = enum_code(record[0], 1)?;
    let kind = enum_code(record[1], 7)?;
    let visible = binary_flag(record[2])?;
    let has_radius = binary_flag(record[11])?;
    if record[9] <= 0.0
        || record[10] <= 0.0
        || (has_radius && record[12] <= 0.0)
        || record[13] < 0.0
        || record[14] < 0.0
    {
        return Err("item dimensions and outline values are invalid");
    }
    if space == SPACE_VIEWPORT
        && (!(0.0..=1.0).contains(&record[15]) || !(0.0..=1.0).contains(&record[16]))
    {
        return Err("viewport anchor coordinates must be in [0, 1]");
    }
    let point_start = index_value(record[19])?;
    let point_count = index_value(record[20])?;
    Ok(ItemInput {
        space,
        kind,
        visible,
        x: record[3],
        y: record[4],
        z: record[5],
        rotation: record[6],
        scale_x: record[7],
        scale_y: record[8],
        width: record[9],
        height: record[10],
        radius: if has_radius { Some(record[12]) } else { None },
        thickness: record[13],
        outline_width: record[14],
        anchor_x: record[15],
        anchor_y: record[16],
        offset_x: record[17],
        offset_y: record[18],
        point_start,
        point_count,
    })
}

fn camera_input(values: &[f64]) -> Result<CameraInput, &'static str> {
    if values.len() != CAMERA_STRIDE || !finite(values) {
        return Err("camera record must contain 9 finite values");
    }
    if values[4] <= 0.0 || values[5] <= 0.0 || values[7] >= values[8] {
        return Err("camera dimensions or depth range are invalid");
    }
    Ok(CameraInput {
        position_x: values[0],
        position_y: values[1],
        offset_x: values[2],
        offset_y: values[3],
        width: values[4],
        height: values[5],
        rotation: values[6],
        near: values[7],
        far: values[8],
    })
}

fn viewport_input(values: &[f64]) -> Result<ViewportInput, &'static str> {
    if values.len() != VIEWPORT_STRIDE || !finite(values) {
        return Err("viewport record must contain 4 finite values");
    }
    if values[2] <= 0.0 || values[3] <= 0.0 {
        return Err("viewport dimensions must be positive");
    }
    Ok(ViewportInput {
        x: values[0],
        y: values[1],
        width: values[2],
        height: values[3],
    })
}

fn enum_code(value: f64, maximum: u8) -> Result<u8, &'static str> {
    if value < 0.0 || value > f64::from(maximum) || value.fract() != 0.0 {
        return Err("item enum code is invalid");
    }
    Ok(value as u8)
}

fn binary_flag(value: f64) -> Result<bool, &'static str> {
    match value {
        0.0 => Ok(false),
        1.0 => Ok(true),
        _ => Err("item flag must be zero or one"),
    }
}

fn index_value(value: f64) -> Result<usize, &'static str> {
    if value < 0.0 || value.fract() != 0.0 || value >= usize::MAX as f64 {
        return Err("point index/count is invalid");
    }
    Ok(value as usize)
}

fn camera_project(x: f64, y: f64, camera: CameraInput, viewport: ViewportInput) -> (f64, f64) {
    let center_x = camera.position_x + camera.offset_x;
    let center_y = camera.position_y + camera.offset_y;
    if camera.rotation == 0.0 {
        let left = center_x - camera.width / 2.0;
        let top = center_y + camera.height / 2.0;
        return (
            viewport.x + (x - left) / camera.width * viewport.width,
            viewport.y + (top - y) / camera.height * viewport.height,
        );
    }

    let delta_x = x - center_x;
    let delta_y = y - center_y;
    let cosine = camera.rotation.cos();
    let sine = camera.rotation.sin();
    let rotated_x = cosine * delta_x + sine * delta_y;
    let rotated_y = -sine * delta_x + cosine * delta_y;
    (
        viewport.x + viewport.width * 0.5 + rotated_x / camera.width * viewport.width,
        viewport.y + viewport.height * 0.5 - rotated_y / camera.height * viewport.height,
    )
}

fn resolved_scales(item: ItemInput, camera: CameraInput, viewport: ViewportInput) -> (f64, f64) {
    if item.space == SPACE_VIEWPORT {
        (
            item.scale_x * camera.width / viewport.width,
            item.scale_y * camera.height / viewport.height,
        )
    } else {
        (item.scale_x, item.scale_y)
    }
}

fn project_item_point(
    item: ItemInput,
    local_x: f64,
    local_y: f64,
    camera: CameraInput,
    viewport: ViewportInput,
) -> (f64, f64) {
    let scaled_x = local_x * item.scale_x;
    let scaled_y = local_y * item.scale_y;
    let angle = item.rotation.to_radians();
    let cosine = angle.cos();
    let sine = angle.sin();
    let offset_x = scaled_x * cosine - scaled_y * sine;
    let offset_y = scaled_x * sine + scaled_y * cosine;
    if item.space == SPACE_VIEWPORT {
        return (
            viewport.x + item.anchor_x * viewport.width + item.offset_x + item.x + offset_x,
            viewport.y + (1.0 - item.anchor_y) * viewport.height
                - item.offset_y
                - item.y
                - offset_y,
        );
    }
    camera_project(item.x + offset_x, item.y + offset_y, camera, viewport)
}

fn item_bounds(
    item: ItemInput,
    points: &[f64],
    camera: CameraInput,
    viewport: ViewportInput,
) -> Result<(f64, f64, f64, f64), &'static str> {
    let point_end = item
        .point_start
        .checked_add(item.point_count)
        .ok_or("point range overflow")?;
    if point_end > points.len() / 2 {
        return Err("item point range exceeds the point buffer");
    }
    if item.kind == KIND_POLYGON && item.point_count < 3 {
        return Err("polygon requires at least three points");
    }
    if item.kind == KIND_LINE && item.point_count != 2 {
        return Err("line requires exactly two points");
    }

    if item.kind == KIND_POLYGON || item.kind == KIND_LINE {
        let mut min_x = f64::INFINITY;
        let mut min_y = f64::INFINITY;
        let mut max_x = f64::NEG_INFINITY;
        let mut max_y = f64::NEG_INFINITY;
        for index in item.point_start..point_end {
            let (x, y) = project_item_point(
                item,
                points[index * 2],
                points[index * 2 + 1],
                camera,
                viewport,
            );
            min_x = min_x.min(x);
            min_y = min_y.min(y);
            max_x = max_x.max(x);
            max_y = max_y.max(y);
        }
        let padding = if item.kind == KIND_LINE {
            let (scale_x, scale_y) = resolved_scales(item, camera, viewport);
            item.thickness * scale_x.abs().max(scale_y.abs()) / camera.width * viewport.width / 2.0
        } else {
            (item.outline_width / 2.0).max(0.5)
        };
        return Ok((
            min_x - padding,
            min_y - padding,
            max_x + padding,
            max_y + padding,
        ));
    }

    let center = project_item_point(item, 0.0, 0.0, camera, viewport);
    let radius_is_extent = matches!(item.kind, KIND_CIRCLE | KIND_POINT) && item.radius.is_some();
    let screen_rotation = if item.space == SPACE_VIEWPORT {
        item.rotation
    } else {
        item.rotation - camera.rotation.to_degrees()
    };
    if !radius_is_extent && screen_rotation != 0.0 {
        let (scale_x, scale_y) = resolved_scales(item, camera, viewport);
        let half_width = (item.width * scale_x).abs() / 2.0;
        let half_height = (item.height * scale_y).abs() / 2.0;
        let corners = [
            (-half_width, -half_height),
            (-half_width, half_height),
            (half_width, -half_height),
            (half_width, half_height),
        ];
        let mut min_x = f64::INFINITY;
        let mut min_y = f64::INFINITY;
        let mut max_x = f64::NEG_INFINITY;
        let mut max_y = f64::NEG_INFINITY;
        for (x, y) in corners {
            // Expra's current Python bounds path scales these corner offsets
            // before project_item_point applies the visual scale again. Keep
            // that operation order for exact first-pass parity.
            let (screen_x, screen_y) = project_item_point(item, x, y, camera, viewport);
            min_x = min_x.min(screen_x);
            min_y = min_y.min(screen_y);
            max_x = max_x.max(screen_x);
            max_y = max_y.max(screen_y);
        }
        return Ok((min_x, min_y, max_x, max_y));
    }

    let (scale_x, scale_y) = resolved_scales(item, camera, viewport);
    let (extent_x, extent_y) = if radius_is_extent {
        let radius =
            item.radius.expect("radius flag is validated") * scale_x.abs().max(scale_y.abs());
        (
            radius / camera.width * viewport.width,
            radius / camera.height * viewport.height,
        )
    } else {
        (
            (item.width * scale_x).abs() / camera.width * viewport.width / 2.0,
            (item.height * scale_y).abs() / camera.height * viewport.height / 2.0,
        )
    };
    Ok((
        center.0 - extent_x,
        center.1 - extent_y,
        center.0 + extent_x,
        center.1 + extent_y,
    ))
}

fn visible_mask(
    records: &[f64],
    points: &[f64],
    camera: CameraInput,
    viewport: ViewportInput,
) -> Result<Vec<bool>, &'static str> {
    if records.len() % ITEM_STRIDE != 0 {
        return Err("item record buffer length is not a multiple of 21");
    }
    if points.len() % 2 != 0 || !finite(points) {
        return Err("point buffer must contain finite x/y pairs");
    }
    let mut mask = Vec::with_capacity(records.len() / ITEM_STRIDE);
    for record in records.chunks_exact(ITEM_STRIDE) {
        let item = item_input(record)?;
        if !item.visible {
            mask.push(false);
            continue;
        }
        if item.space != SPACE_WORLD && item.space != SPACE_VIEWPORT {
            return Err("item coordinate space is invalid");
        }
        if item.z < camera.near || item.z > camera.far {
            mask.push(false);
            continue;
        }
        let (left, top, right, bottom) = item_bounds(item, points, camera, viewport)?;
        mask.push(
            right >= viewport.x
                && left <= viewport.x + viewport.width
                && bottom >= viewport.y
                && top <= viewport.y + viewport.height,
        );
    }
    Ok(mask)
}

#[cfg(feature = "python-extension")]
use pyo3::exceptions::PyValueError;
#[cfg(feature = "python-extension")]
use pyo3::prelude::*;

#[cfg(feature = "python-extension")]
#[pyfunction]
#[pyo3(name = "visible_mask")]
fn visible_mask_py(
    records: Vec<f64>,
    points: Vec<f64>,
    camera_values: Vec<f64>,
    viewport_values: Vec<f64>,
) -> PyResult<Vec<bool>> {
    let camera = camera_input(&camera_values).map_err(PyValueError::new_err)?;
    let viewport = viewport_input(&viewport_values).map_err(PyValueError::new_err)?;
    visible_mask(&records, &points, camera, viewport).map_err(PyValueError::new_err)
}

#[cfg(feature = "python-extension")]
#[pymodule]
fn expra_render_math(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(visible_mask_py, module)?)?;
    Ok(())
}

#[cfg(test)]
mod tests;
