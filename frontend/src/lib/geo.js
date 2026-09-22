/** Flatten every coordinate pair out of a Polygon/MultiPolygon geometry. */
function allPositions(geometry) {
  if (!geometry) return [];
  const { type, coordinates } = geometry;
  if (type === "Polygon") return coordinates.flat();
  if (type === "MultiPolygon") return coordinates.flat(2);
  if (type === "Point") return [coordinates];
  return [];
}

/** Simple average-of-vertices centroid -- good enough for small, roughly
 * convex demo zones; not an area-weighted centroid. Returns [lat, lon] or
 * null. GeoJSON stores [lon, lat], so the order is swapped here. */
export function geometryCentroid(geometry) {
  const positions = allPositions(geometry);
  if (!positions.length) return null;
  const [lonSum, latSum] = positions.reduce(
    ([lo, la], [lon, lat]) => [lo + lon, la + lat],
    [0, 0]
  );
  return [latSum / positions.length, lonSum / positions.length];
}

/** GeoJSON Polygon/MultiPolygon coordinates -> Leaflet's [lat,lon] ring
 * format, for react-leaflet's <Polygon positions={...}/>. */
export function toLeafletPositions(geometry) {
  if (!geometry) return [];
  const swap = (ring) => ring.map(([lon, lat]) => [lat, lon]);
  if (geometry.type === "Polygon") return geometry.coordinates.map(swap);
  if (geometry.type === "MultiPolygon")
    return geometry.coordinates.map((poly) => poly.map(swap));
  return [];
}
