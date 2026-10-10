package vn.vast.vasteq.user;

import java.net.URI;
import io.quarkus.security.Authenticated;
import io.smallrye.common.annotation.Blocking;
import jakarta.annotation.security.PermitAll;
import jakarta.annotation.security.RolesAllowed;
import jakarta.inject.Inject;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import jakarta.ws.rs.*;
import jakarta.ws.rs.core.*;
import org.eclipse.microprofile.jwt.JsonWebToken;

@Path("/api/v1/user")
@Produces(MediaType.APPLICATION_JSON)
@Consumes(MediaType.APPLICATION_JSON)
@Authenticated
@Blocking
public class UserResource {
    @Inject UserService service;
    @Inject JsonWebToken jwt;
    @POST @Path("/register") @PermitAll
    public Response register(@NotNull @Valid UserDtos.Register request){
        var user=service.register(request);return Response.created(URI.create("/api/v1/user/me")).entity(user).build();
    }
    @POST @Path("/login") @PermitAll
    public Response login(@NotNull @Valid UserDtos.Login request){
        return Response.ok(service.login(request)).header("Cache-Control","no-store").header("Pragma","no-cache").build();
    }
    @GET @Path("/me") public UserDtos.View me(){return service.me(jwt);}
    @PATCH @Path("/me") public UserDtos.View profile(@NotNull @Valid UserDtos.Profile request){return service.profile(jwt,request);}
    @PUT @Path("/me/password") public Response password(@NotNull @Valid UserDtos.PasswordChange request){service.changePassword(jwt,request);return Response.noContent().build();}
    @GET @RolesAllowed("admin") public UserDtos.Page list(@QueryParam("offset") @DefaultValue("0") @Min(0) int offset,@QueryParam("limit") @DefaultValue("20") @Min(1) @Max(100) int limit){return service.list(jwt,offset,limit);}
    @POST @RolesAllowed("admin") public Response create(@NotNull @Valid UserDtos.AdminCreate request){var user=service.create(jwt,request);return Response.created(URI.create("/api/v1/user/"+user.id())).entity(user).build();}
    @GET @Path("/{id}") @RolesAllowed("admin") public UserDtos.View get(@PathParam("id") @Min(1) long id){return service.get(jwt,id);}
    @PATCH @Path("/{id}") @RolesAllowed("admin") public UserDtos.View update(@PathParam("id") @Min(1) long id,@NotNull @Valid UserDtos.AdminUpdate request){return service.update(jwt,id,request);}
    @DELETE @Path("/{id}") @RolesAllowed("admin") public Response disable(@PathParam("id") @Min(1) long id){service.disable(jwt,id);return Response.noContent().build();}
}
