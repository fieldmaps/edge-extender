# Polygon to Voronoi

This tool takes polygons as inputs and applies a voronoi algorithm along the edges, giving results similar to a euclidean allocation distance raster. Unlike euclidean allocation, the source is never transformed from vector to raster. All internal polygon topology remains unchanged, with the exception of internal holes which are filled in the same way the exterior is filled out.

## Usage

Currently, supported inputs are polygon layers in GeoPackage (.gpkg), Shapefile (.shp), or GeoJSON (.geojson) formats. For GeoPackages, all polygon layers inside are processed. Outputs retain their original format, projected to EPSG:4326 (WGS84). To get started, add files to the `inputs` directory, where they're processed in parallel into `outputs`. Make sure docker is installed and running, and run `docker-compose up`. For those on Linux or macOS who want to process outside of docker for more native performance, install GDAL and PostGIS with a polygon_voronoi table. After that, run `python3 -m processing` from this directory. Polygons the size of small countries typically take a few minutes, with larger ones taking upwards of 30 min using default settings. Processing time is proportional to total perimiter length rather than area.

## Configuration

There are three user configurable variables defined in `config.ini`. The first is a `dissolve` field. By default, this is set to `fid` which doesn't dissolve the output. This field is the default primary ID for GeoPackages, and is automatically added to Shapefiles and GeoJSON if missing. The second option is a `precision` value, set to `0.0001` (approx 10m) by default. This is used as the distance interval points are set along lines for the voronoi algorithm, in addition to existing line verticies. This value is chosen to be similar to the resolution of satellite imagery, sometimes used for automatically digitizing shorelines in some boundaries. For planet level geometry, a smaller precision (0.001) helps the algorithm run faster and use less memory. For smaller areas, a higher precision (0.00001) ensures the allocation is as accurate as possible, but takes longer and may fail if there is insufficient system memory. The final valiable is for `snap`, which fixes the precision of points generated along the edges to account for errors caused by spurious precision in geometries. This should rarely be changed, and is set to a default of `0.000001` (approx 0.1m), providing a good tradeoff between speed and accuracy for most inputs. Note that snapping only occurs for points used to generate voronoi polygons. Internal polygon boundaries are unaffected by this and maintain original precision.

## How it Works

The overall processing can be broken down into 4 distinct types of geometry transformations:

- make lines from polygons
- make points from lines
- make voronoi from points
- merge polygons with voronoi

**Polygon to Line:** The first part extracts outlines from the polygon, first by dissolving all polygons together, then by taking the intersection between the outline of the dissolved and the original layer. By intersecting these two together, it retains attribute information of where segments originate from.

|   Original Input    |      Outlines       |
| :-----------------: | :-----------------: |
| ![](img/tza_01.png) | ![](img/tza_02.png) |

**Line to Point:** Lines are converted to points using two methods. The first set of points are taken from all verticies that make up a line. However, for certain areas like winding rivers and deltas, this in an insufficient level of detail to properly center the resulting voronoi. With just verticies, the center lines would zigzag through gaps instead of going straight through them. Lines are therefore split up into segments based on a configurable distance, with verticies taken at the breaks between segments.

| Points along River  | Final Result along Delta |
| :-----------------: | :----------------------: |
| ![](img/tza_03.png) |   ![](img/tza_04.png)    |

**Point to Voronoi:** For country sized inputs, there may be hundreds of thousands, if not millions of individual voronoi polygons created in this step. Because each individual section retains attribute information of what polygon it originated from, they can be dissolved together to a simplified output.

| Points with Voronoi |    Voronoi Only     |
| :-----------------: | :-----------------: |
| ![](img/tza_05.png) | ![](img/tza_06.png) |

**Polygon-Voronoi Merge:** The original polygon is overlayed in a union with the voronoi. Boundaries from the inner area are kept from the original, dissolved with polygons containing matching attributes from the outside area. The dissolved layer is the final output of the tool.

| Original over Voronoi |    Final Output     |
| :-------------------: | :-----------------: |
|  ![](img/tza_07.png)  | ![](img/tza_08.png) |

## Use Case 1: Matching sub-national boundary (ADM3) to national (ADM0)

One original use case for this tool was resolving edge differences between different levels of administrative boundaries where some layers included water bodies but others did not. The United Republic of Tanzania is used in this example as it contains many elements that have been difficult to resolve in the past: lakes along international boundaries, internal water bodies shared by multiple areas, groups of islands, etc. The diagram on the left shows how the ADM3 layer would appear in a global edge-matched geodatabase. The diagram on the right shows how water areas are allocated compared to the original.

|  ADM0 over Voronoi  | Original vs ADM0 edges |
| :-----------------: | :--------------------: |
| ![](img/tza_09.png) |  ![](img/tza_10.png)   |

## Use Case 2: Topologically clean international boundaries

The other original use case envisioned for this tool is resolving edges between boundaries where there are significant gaps or overlaps. Where this occurs, a separate topologically clean layer is required to set boundary lines, after which the process is similar to the above.

| Topologically clean ADM0 with areas of interest |
| :---------------------------------------------: |
|               ![](img/tri_00.png)               |

| Original boundaries | Clipped voronoi boundaries |
| :-----------------: | :------------------------: |
| ![](img/tri_01.png) |    ![](img/tri_02.png)     |

| Original boundaries (tri-point) | Clipped voronoi boundaries (tri-point) |
| :-----------------------------: | :------------------------------------: |
|       ![](img/tri_03.png)       |          ![](img/tri_04.png)           |

## Use Case 3: Improving coastlines

The use case above demonstrates how useful it is to have a topologically clean global ADM0 layer. Very few protray disputed areas properly, and for those that do portray accurate internal boundaries, coastlines may lack in detail compared to other sources. OpenStreetMap has very detailed coastline data available as Shapefiles, and this can be integrated with ADM0 datasets in the same way as above.

| World ADM0 with Voronoi |    Voronoi Only     |
| :---------------------: | :-----------------: |
|   ![](img/wld_01.png)   | ![](img/wld_02.png) |

|    Original ADM0    | Coastline replaced with OpenStreetMap |
| :-----------------: | :-----------------------------------: |
| ![](img/wld_03.png) |          ![](img/wld_04.png)          |

## Potential Issues

In earlier versions of this tool, vector inputs created from raster sources were known to present issues in rare cases. In the PostGIS implementation of voronoi polygons, inputs in a regular grid can sometimes result in polygon outputs with invalid geometry, giving one of the following errors:

- lwgeom_unaryunion_prec: GEOS Error: TopologyException: unable to assign free hole to a shell
- GEOSVoronoiDiagram: TopologyException: Input geom 1 is invalid: Self-intersection
- processing.voronoi runs at 300% CPU for more than 30 min

Significant effort has been taken to prevent this from occuring in current versions of this tool. However, if this does occur, first try reducing the segment interval to a value that generates valid outputs, a value of 0.0003 usually works. If this still doesn't work after reducing precision even further, trying to reduce the snap precision should help too. If still failing, the issue may be related to topological errors in the original input, and it may need to be cleaned before processing, as only basic validity checks are done on import.

| Possible Error (segment=0.0001) | Succeeds (segment=0.0003) |
| :-----------------------------: | :-----------------------: |
|       ![](img/err_01.png)       |    ![](img/err_02.png)    |
