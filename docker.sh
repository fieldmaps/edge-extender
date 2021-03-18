docker build -t fieldmaps/polygon-voronoi .
docker image prune --force

docker run --rm \
  -v $(pwd)/inputs:/usr/src/app/inputs \
  -v $(pwd)/outputs:/usr/src/app/outputs \
  fieldmaps/polygon-voronoi
