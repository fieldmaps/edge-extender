# Polygon Voronoi

This tool takes a polygon as input and applies a voronoi algorithm along the edges, giving a result similar to a euclidean allocation distance raster. Unlike euclidean allocation, the source is never transformed from vector to raster. All internal polygon topolygy remains unchanged, with the exception of internal holes which are filled in the same way the exterior is filled out.

## Usage

Currently, GeoPackage (GPKG) and Shapefile (SHP) are supported input formats, with outputs in EPSG:4326 (WGS84). Running the tool requires files to be added to the `inputs` directory, where they will be processed in parallel. Resulting files are added to an `outputs` folder. `docker.sh` is included with some simple commands for building an image and running a container, ensuring the inputs and outputs folders are bound between the host system and the docker container. For those on Linux or macOS who want to run processing outside of docker, install GDAL and PostGIS with a `polygon_voronoi` table created. After that, the tool can be invoked with `python3 -m processing`.

## Configuration

There are two user configurable varibles defined in `config.ini`. The first is a `dissolve` field. By default this is set to `fid`, which will not dissolve the output. This field is already present on GeoPackages, and is automatically added to Shapefiles on import. The second option is a `precision` value, set to `0.0001` by default. This decimal degree value is equivilent to roughly 10m, and is used as the interval points are set along the edges for the voronoi algorithm. For planet level geometry, a smaller precision will help the algorith run faster. For smaller areas, a higher precision will ensure the allocation is as accurate as possible.
