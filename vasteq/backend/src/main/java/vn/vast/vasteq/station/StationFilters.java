package vn.vast.vasteq.station;

import jakarta.validation.constraints.*;
import jakarta.ws.rs.*;

public class StationFilters {
    @QueryParam("offset") @DefaultValue("0") @Min(0) public int offset;
    @QueryParam("limit") @DefaultValue("20") @Min(1) @Max(100) public int limit;
    @QueryParam("networkCode") @Size(max=2) public String networkCode;
    @QueryParam("stationCode") @Size(max=5) public String stationCode;
    @QueryParam("province") @Size(max=120) public String province;
    @QueryParam("city") @Size(max=120) public String city;
    @QueryParam("hasCoordinates") @Pattern(regexp="true|false") public String hasCoordinates;
    @QueryParam("search") @Size(max=120) public String search;
}
