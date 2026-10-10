package vn.vast.vasteq.user;

import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import jakarta.persistence.LockModeType;
import jakarta.persistence.PersistenceException;
import jakarta.transaction.Transactional;
import org.eclipse.microprofile.jwt.JsonWebToken;
import org.hibernate.exception.ConstraintViolationException;

@ApplicationScoped
@Transactional
public class UserService {
    @Inject UserRepository repository;
    @Inject PasswordHasher passwords;
    @Inject TokenService tokens;
    @Inject AccountAccess access;
    private String dummyHash;

    private synchronized String dummyHash() {
        if(dummyHash==null)dummyHash=passwords.hash("dummy-password-do-not-use");
        return dummyHash;
    }
    private ApiException unauthorized(){return new ApiException(401,"unauthorized","Authentication required or credentials invalid");}
    private User actor(JsonWebToken jwt,boolean admin) {
        return access.require(jwt,admin);
    }
    private User required(long id) {
        User user=repository.findById(id);
        if(user==null)throw new ApiException(404,"user_not_found","Account not found");
        return user;
    }
    private void availableEmail(String email,Long exceptId) {
        User existing=repository.byEmail(email);
        if(existing!=null && !existing.id.equals(exceptId))throw new ApiException(409,"email_exists","An account with this email already exists");
    }
    private void flush() {
        try{repository.flush();}
        catch(PersistenceException e){
            for(Throwable cause=e;cause!=null;cause=cause.getCause()){
                if(cause instanceof ConstraintViolationException violation){
                    String state=violation.getSQLState();
                    if("23505".equals(state) || violation.getErrorCode()==1062)
                        throw new ApiException(409,"email_exists","An account with this email already exists");
                }
            }
            throw e;
        }
    }
    private User createUser(String email,String password,String name,User.Role role) {
        availableEmail(email,null);
        User user=new User();user.email=email;user.passwordHash=passwords.hash(password);
        user.displayName=name;user.role=role;
        // IDENTITY generation can perform the insert during persist, before flush.
        try{repository.persist(user);flush();}
        catch(PersistenceException e){
            for(Throwable cause=e;cause!=null;cause=cause.getCause())
                if(cause instanceof ConstraintViolationException violation && (violation.getErrorCode()==1062 || "23505".equals(violation.getSQLState())))
                    throw new ApiException(409,"email_exists","An account with this email already exists");
            throw e;
        }
        return user;
    }
    public UserDtos.View register(UserDtos.Register request) {
        return createUser(request.email(),request.password(),request.displayName(),User.Role.user).view();
    }
    public UserDtos.Token login(UserDtos.Login request) {
        User user=repository.byEmail(request.email());
        boolean valid=passwords.verify(request.password(),user==null?dummyHash():user.passwordHash);
        if(!valid || user==null || !user.enabled)throw unauthorized();
        return tokens.issue(user);
    }
    public UserDtos.View me(JsonWebToken jwt){return actor(jwt,false).view();}
    public UserDtos.View profile(JsonWebToken jwt,UserDtos.Profile request){
        if(request.email()==null && request.displayName()==null)throw new ApiException(400,"empty_update","Provide email or displayName");
        User user=actor(jwt,false);
        if(request.email()!=null){availableEmail(request.email(),user.id);user.email=request.email();}
        if(request.displayName()!=null)user.displayName=request.displayName();
        flush();return user.view();
    }
    public void changePassword(JsonWebToken jwt,UserDtos.PasswordChange request){
        User user=actor(jwt,false);
        if(!passwords.verify(request.currentPassword(),user.passwordHash))throw unauthorized();
        user.passwordHash=passwords.hash(request.newPassword());flush();
    }
    public UserDtos.Page list(JsonWebToken jwt,int offset,int limit){
        actor(jwt,true);
        if((long)offset+limit-1>Integer.MAX_VALUE)throw new ApiException(400,"invalid_pagination","Offset plus limit exceeds the supported range");
        return new UserDtos.Page(repository.find("order by id").range(offset,offset+limit-1).list().stream().map(User::view).toList(),repository.count(),offset,limit);
    }
    public UserDtos.View get(JsonWebToken jwt,long id){actor(jwt,true);return required(id).view();}
    public UserDtos.View create(JsonWebToken jwt,UserDtos.AdminCreate request){
        actor(jwt,true);
        return createUser(request.email(),request.password(),request.displayName(),request.role()==null?User.Role.user:User.Role.valueOf(request.role())).view();
    }
    public UserDtos.View update(JsonWebToken jwt,long id,UserDtos.AdminUpdate request){
        if(request.email()==null && request.displayName()==null && request.role()==null && request.enabled()==null)
            throw new ApiException(400,"empty_update","Provide at least one field");
        int admins=repository.find("role=?1 and enabled=true order by id",User.Role.admin).withLock(LockModeType.PESSIMISTIC_WRITE).list().size();
        actor(jwt,true);User user=required(id);
        User.Role role=request.role()==null?user.role:User.Role.valueOf(request.role());
        boolean enabled=request.enabled()==null?user.enabled:request.enabled();
        if(user.role==User.Role.admin && user.enabled && (role!=User.Role.admin || !enabled) && admins<=1)
            throw new ApiException(409,"last_admin","The last active administrator cannot be disabled or demoted");
        if(request.email()!=null){availableEmail(request.email(),user.id);user.email=request.email();}
        if(request.displayName()!=null)user.displayName=request.displayName();
        user.role=role;user.enabled=enabled;flush();return user.view();
    }
    public void disable(JsonWebToken jwt,long id){update(jwt,id,new UserDtos.AdminUpdate(null,null,null,false));}
}
