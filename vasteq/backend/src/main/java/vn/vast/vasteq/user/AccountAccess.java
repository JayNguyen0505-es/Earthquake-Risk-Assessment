package vn.vast.vasteq.user;

import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.eclipse.microprofile.jwt.JsonWebToken;

/** Check current account state as well as the JWT role claims. */
@ApplicationScoped
public class AccountAccess {
    @Inject UserRepository repository;

    public User require(JsonWebToken jwt, boolean admin) {
        long id;
        try {
            id = Long.parseLong(jwt.getSubject());
        } catch (RuntimeException e) {
            throw unauthorized();
        }
        User user = repository.findById(id);
        if (user == null || !user.enabled) throw unauthorized();
        if (admin && user.role != User.Role.admin)
            throw new ApiException(403, "forbidden", "Administrator access required");
        return user;
    }

    private ApiException unauthorized() {
        return new ApiException(401, "unauthorized", "Authentication required or credentials invalid");
    }
}
