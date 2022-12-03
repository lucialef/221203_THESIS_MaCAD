## IMPORT LIBRARIES 
import pandas as pd
import geopandas as gpd
import pandana as pdn
import geopy
from geopy import Nominatim
from shapely.geometry import LineString
from sklearn.preprocessing import minmax_scale

def getRoutes(JSON_month, JSON_start, JSON_end):

    ##### ---------- LOAD PREPROCESSED DATA ---------- #####
    # DF ALREADY PROJECTED IN CRS 3857 - READ DOCUMENTATION TO ENLARGED THIS STEP

    ## 1/ LOAD NETWORK AS NX GRAPH
    filepath_nodes = './load/nodes.shp'
    filepath_edges = './load/edges.shp'
    nodes = gpd.read_file(filepath_nodes)
    edges = gpd.read_file(filepath_edges)

    ## 2/ LOAD TREES DATASET
    filepath_trees = './load/trees_proj.shp'
    tr_proj = gpd.read_file(filepath_trees)

    ## 3/ LOAD BLOOM DATASET
    filepath_bloom = './load/FLOWERING_SEV_trees.csv'
    bloom_df = pd.read_csv(filepath_bloom)

    ## 4/ DEFINE NETWORK CRS
    crs_proj = 3857


    ##### ---------- CREATE MONTH FILTER ---------- #####
    # encode the column to mask
    season = JSON_month
    ## FILTER TREE DATASET PER MONTH
    # display mask
    mask = bloom_df[season].isin([1.0])
    # PD series to PD DF
    bloom_mask = bloom_df[mask].copy()
    # clean DF
    bloom_cl = bloom_mask[['NAME', season]].copy()
    # join trees DF and filtered DF on family column
    tr_join = pd.merge(tr_proj, bloom_cl, how='left', on='NAME')
    # filter trees DF by dropping NAN rows
    tr_season = tr_join.dropna() 
    # ---> OUTPUT 01: save seasonal trees as json
    tr_season_geojson = tr_season.to_json()



    ##### ---------- DEFINE ORIGIN & DESTINY ---------- #####
    ## DEFINE REVERSE GEOCODE FUNCTION
    def get_location_data(lat, lon):
        locator = Nominatim(user_agent="gds4ae")
        coords = (lat, lon)
        location = locator.reverse(coords)
            
        return location.address

    ## DEFINE PATH LOCATIONS
    geopy.geocoders.options.default_user_agent = "gds4ae"

    # source / origin
    split_coord_start = [j.split() for j in JSON_start.split(',') if j!='']
    split_coord_start = [item for sublist in split_coord_start for item in sublist]
    split_coord_start = [float(i) for i in split_coord_start]
    lat_coord_start = split_coord_start[0::2]
    lon_coord_start = split_coord_start[1::2]

    JSON_start_x = float(lon_coord_start[0])
    JSON_start_y = float(lat_coord_start[0])

    start_address = get_location_data(JSON_start_x, JSON_start_y)
    orig_address = gpd.tools.geocode(start_address, geopy.Nominatim).to_crs(crs_proj)

    # target / destiny
    split_coord_end = [j.split() for j in JSON_end.split(',') if j!='']
    split_coord_end = [item for sublist in split_coord_end for item in sublist]
    split_coord_end = [float(i) for i in split_coord_end]
    lat_coord_end = split_coord_end[0::2]
    lon_coord_end = split_coord_end[1::2]

    JSON_end_x = float(lat_coord_end[0])
    JSON_end_y = float(lon_coord_end[0])

    end_address = get_location_data(JSON_end_y, JSON_end_x)
    dest_address = gpd.tools.geocode(end_address, geopy.Nominatim).to_crs(crs_proj)

    # ---> OUTPUT 04: save directions as json
    orig_address_geojson = orig_address.to_json()
    dest_address_geojson = dest_address.to_json()



    ##### ---------- PANDANA ROUTE FUNCTION ---------- #####
    # BUILD LINESTRING FROM NODES MANUALLY
    def route_nodes_to_line(nodes, network):
        pts = network.nodes_df.loc[nodes, :]
        s = gpd.GeoDataFrame(
            {"src_node": [nodes[0]], "tgt_node": [nodes[1]]},
            geometry=[LineString(pts.values)],
            crs=crs_proj
        )
        return s



    ##### ---------- PANDANA SHORTEST ROUTE ---------- #####
    # create PDN graph to calculate the SHORTEST ROUTE based on EDGES LENGTH
    streets_pdn = pdn.Network(
                nodes.geometry.x,
                nodes.geometry.y,
                edges["node_start"],
                edges["node_end"],
                edges[["mm_len"]]
    )
    # snap A & B points to closest node on graph
    pt_nodes = streets_pdn.get_node_ids(
        [orig_address.geometry.x, dest_address.geometry.x], 
        [orig_address.geometry.y, dest_address.geometry.y]
    )
    # route the shortest path
    route_nodes = streets_pdn.shortest_path(pt_nodes[0], pt_nodes[1])
    # build shortest route linestring
    short_path = route_nodes_to_line(route_nodes, streets_pdn)
    # get route length in KM
    short_path_len = streets_pdn.shortest_path_length(
        pt_nodes[0], pt_nodes[1]
    )
    short_path_km = round(short_path_len / 1000, 3) # Dist in Km, 3 digits
    # ---> OUTPUT 02: save seasonal route as json
    short_path_geojson = short_path.to_json()



    ##### ---------- PANDANA SEASONAL ROUTE ---------- #####
    # weight the seasonal path / the bigger the number, the higher priority to AMOUNT OF TREES Vs. DISTANCE
    power = 1000

    ## PREPROCESSING
    # snap trees to PDN network - get closest node IDS
    tr_nodes = tr_season.copy()
    tr_nodes['node_ids'] = streets_pdn.get_node_ids(tr_nodes['lon'], tr_nodes['lat'])
    # create PD series to count node occurrences and convert to PD DF
    tr_count = tr_nodes['node_ids'].value_counts()
    tr_count_df = pd.DataFrame(tr_count)
    # clean DF
    tr_count_df = tr_count_df.rename(columns={'node_ids': 'trees'})
    # create node ID column from index
    tr_count_df.reset_index(inplace=True)
    # duplicate count DF as node start
    tr_count_st = tr_count_df.copy()
    tr_count_st = tr_count_st.rename(columns={'index': 'node_start', 'trees': 'trees_start'})
    # duplicate count DF as node end
    tr_count_end = tr_count_df.copy()
    tr_count_end = tr_count_end.rename(columns={'index': 'node_end', 'trees': 'trees_end'})
    # join PDN graph edges and trees occurrences DF
    w_edges = pd.merge(edges, tr_count_st, how='left', on='node_start')
    w_edges = pd.merge(w_edges, tr_count_end, how='left', on='node_end')
    # add column to PDN EDGES with the total amount of trees per edge
    w_edges['trees_total']= w_edges['trees_start'] + w_edges['trees_end']
    # replace NAN values with 0
    w_edges['trees_total'].fillna(0, inplace=True) 
    # attach to edges a scaled version of "mm_len"
    w_edges["scaled_len"] = minmax_scale(w_edges["mm_len"])
    # attach to edges a scaled negative version of the amount of trees / a street with more trees snapped will have a "shortest length"
    w_edges["scaled_trees"] = minmax_scale(-w_edges["trees_total"])
    # define the weighted column for routes calcultion
    w_edges["tr_len"] = w_edges["length"] * (w_edges["scaled_trees"]**power)

    # CALCULATE SEASONAL ROUTE
    # create PDN graph to calculate the SEASONAL ROUTE based on AM. OF TREES
    season_pdn = pdn.Network(
                        nodes.geometry.x,
                        nodes.geometry.y,
                        w_edges["node_start"],
                        w_edges["node_end"],
                        w_edges[["tr_len"]]
    )
    # snap A & B points to closest node on graph
    pt_tr_nodes = season_pdn.get_node_ids(
        [orig_address.geometry.x, dest_address.geometry.x], 
        [orig_address.geometry.y, dest_address.geometry.y]
    )
    # route the seasonal path
    w_route_nodes = season_pdn.shortest_path(pt_tr_nodes[0], pt_tr_nodes[1])
    # build seasonal route linestring
    season_path = route_nodes_to_line(w_route_nodes, season_pdn)
    # ---> OUTPUT 03: save seasonal route as json
    season_path_geojson = season_path.to_json()

    #### return to APP.PY
    return season_path_geojson, short_path_geojson, tr_season_geojson, orig_address_geojson, dest_address_geojson