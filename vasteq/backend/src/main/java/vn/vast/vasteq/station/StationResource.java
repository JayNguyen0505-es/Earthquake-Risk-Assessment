package vn.vast.vasteq.station;

import java.net.URI;
import com.fasterxml.jackson.databind.JsonNode;
import io.quarkus.security.Authenticated;
import io.smallrye.common.annotation.Blocking;
import jakarta.annotation.security.RolesAllowed;
import jakarta.inject.Inject;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import jakarta.ws.rs.*;
import jakarta.ws.rs.core.*;
import org.eclipse.microprofile.jwt.JsonWebToken;

@Path("/api/v1/station")
@Produces(MediaType.APPLICATION_JSON)
@Consumes(MediaType.APPLICATION_JSON)
@Authenticated
@Blocking
public class StationResource {
    @Inject StationService service;
    @Inject JsonWebToken jwt;

    @GET
    public StationService.Page list(@BeanParam @Valid StationFilters filters) {
        return service.list(jwt, filters);
    }

    @GET @Path("/{id}")
    public Station get(@PathParam("id") @Min(1) long id) { return service.get(jwt, id); }

    @POST @RolesAllowed("admin")
    public Response create(@NotNull @Valid StationInput input) {
        Station station = service.create(jwt, input);
        return Response.created(URI.create("/api/v1/station/" + station.id)).entity(station).build();
    }

    @PATCH @Path("/{id}") @RolesAllowed("admin")
    public Station update(@PathParam("id") @Min(1) long id, @NotNull JsonNode patch) {
        return service.update(jwt, id, patch);
    }

    @DELETE @Path("/{id}") @RolesAllowed("admin")
    public Response delete(@PathParam("id") @Min(1) long id) {
        service.delete(jwt, id);
        return Response.noContent().build();
    }
}
