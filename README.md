# Polygon to Voronoi

This tool takes a polygon as input and applies a voronoi algorithm along the edges, giving a result similar to a euclidean allocation distance raster. Unlike euclidean allocation, the source is never transformed from vector to raster. All internal polygon topology remains unchanged, with the exception of internal holes which are filled in the same way the exterior is filled out.

## Usage

Currently, supported inputs are polygon layers in GeoPackage (.gpkg), Shapefile (.shp), or GeoJSON (.geojson) formats. For GeoPackages, all polygon layers inside will be processed. Outputs will retain their original format, but will be projected to EPSG:4326 (WGS84). Running the tool requires files to be added to the `inputs` directory, where they will be processed in parallel into the `outputs` directory. To use the tool, make sure docker is installed and running. From the command line, navigate to this directory and run `docker-compose up`. For those on Linux or macOS who want to run processing outside of docker, install GDAL and PostGIS with a `polygon_voronoi` table. After that, run `python3 -m processing` from this directory.

## Configuration

There are two user configurable variables defined in `config.ini`. The first is a `dissolve` field. By default, this is set to `fid` which will not dissolve the output. This field is the default primary ID for GeoPackages, and is automatically added to Shapefiles and GeoJSON if missing. The second option is a `precision` value, set to `0.0001` by default. This decimal degree value is equivalent to roughly 10m, and is used as the interval points are set along the edges for the voronoi algorithm. For planet level geometry, a smaller precision (`0.01`) will help the algorithm use less memory and run faster. For smaller areas, a higher precision (`0.000001`) will ensure the allocation is as accurate as possible but will take longer and may fail if there is insufficient system memory.
